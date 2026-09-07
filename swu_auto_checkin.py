#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import json
import argparse
import shutil
import logging
from typing import Tuple, Optional, Any, Dict
from contextlib import contextmanager
from pathlib import Path

import requests
import ddddocr
from DrissionPage import ChromiumPage, ChromiumOptions

# ==================== 日志配置 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== 配置常量 ====================
CHECKIN_TIME_RANGE = ["21:00", "23:30"]          # 打卡时间段（文件二固定值）
MAX_RETRIES = 3
LOGIN_URL = (
    'https://of.swu.edu.cn/cas/oauth/login/SWU_CAS2_FEDERAL'
    '?service=https%3A%2F%2Fof.swu.edu.cn%2Fgateway%2Ffighter-middle%2Fapi%2Fintegrate%2Fuaap%2Fcas%2Fresolve-cas-return'
    '%3Fnext%3Dhttps%253A%252F%252Fof.swu.edu.cn%252F%2523%252FcasLogin%253Ffrom%253D%25252FappCenter'
)
BASE_LOGIN_URL = 'https://idm.swu.edu.cn/am/UI/Login'
API_USER_URL = 'https://of.swu.edu.cn/gateway/fighter-middle/api/auth/user?appType=fighter-portal'
API_TASK_URL = 'https://of.swu.edu.cn/gateway/fighter-baida/api/cqtj/getTransitionByToday'
API_CHECKIN_URL = 'https://of.swu.edu.cn/gateway/fighter-baida/api/form-instance/save'
CAPTCHA_IMG_DIR = Path('images')
CAPTCHA_IMG_PATH = CAPTCHA_IMG_DIR / 'captcha.png'
TIMEOUT_PAGE_LOAD = 30
TIMEOUT_API = 15
ELEMENT_TIMEOUT = 10

# ==================== 工具函数（来自文件一） ====================
def get_chrome_path() -> str:
    """获取 Chrome/Chromium 可执行文件路径（兼容 Windows）"""
    env_path = os.environ.get('CHROME_PATH')
    if env_path and os.path.isfile(env_path):
        return str(env_path)

    possible_paths = [
        '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable',
        '/usr/bin/chromium-browser', '/usr/bin/chromium',
        '/opt/google/chrome/chrome',
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for path in possible_paths:
        if os.path.isfile(path):
            return str(path)

    for cmd in ('google-chrome', 'chrome'):
        chrome_cmd = shutil.which(cmd)
        if chrome_cmd:
            return str(chrome_cmd)

    raise RuntimeError("❌ 未找到 Chrome 浏览器，请设置 CHROME_PATH 环境变量")

def remove_captcha_image() -> None:
    """清理验证码图片和目录"""
    try:
        if CAPTCHA_IMG_PATH.exists():
            CAPTCHA_IMG_PATH.unlink()
        if CAPTCHA_IMG_DIR.exists() and not any(CAPTCHA_IMG_DIR.iterdir()):
            CAPTCHA_IMG_DIR.rmdir()
    except OSError as e:
        logger.debug(f"清理验证码文件时忽略异常: {e}")

@contextmanager
def browser_page(headless: bool = False) -> Any:
    """浏览器上下文管理器（来自文件一）"""
    chrome_path = get_chrome_path()
    is_ci = os.environ.get('GITHUB_ACTIONS') == 'true'
    use_headless = headless or is_ci

    co = ChromiumOptions()
    co.set_browser_path(chrome_path)
    co.set_argument('--window-size=1920,1080')
    co.set_argument('--no-sandbox')
    co.set_argument('--disable-gpu')
    co.set_argument('--disable-dev-shm-usage')
    co.set_argument('--disable-cache')
    co.set_argument('--disable-application-cache')
    if use_headless:
        co.set_argument('--headless=new')
        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument(
            '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )

    page = ChromiumPage(co)
    try:
        yield page
    finally:
        try:
            page.quit()
        except Exception as e:
            logger.warning(f"关闭浏览器时忽略异常: {e}")

def find_element(page: ChromiumPage, *selectors: Any, timeout: int = ELEMENT_TIMEOUT):
    """通用元素查找，支持多种选择器（包括 lambda）"""
    for sel in selectors:
        try:
            if callable(sel):
                el = sel(page)
            else:
                el = page.ele(sel, timeout=timeout)
            if el:
                return el
        except Exception:
            continue
    return None

def find_input(page: ChromiumPage, selectors: list, timeout: int = ELEMENT_TIMEOUT):
    """简化输入框查找，传入选择器列表"""
    return find_element(page, *selectors, timeout=timeout)

def api_request(method: str, url: str, token: str,
                params: Optional[Dict] = None,
                data: Optional[Dict] = None,
                json_data: Optional[Dict] = None) -> Dict:
    """统一的 API 请求封装（文件一）"""
    headers = {"fighter-auth-token": token}
    if json_data is not None:
        headers["Content-Type"] = "application/json;charset=UTF-8"

    resp = None
    try:
        resp = requests.request(
            method, url, headers=headers, params=params,
            data=data, json=json_data, timeout=TIMEOUT_API
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        error_detail = ""
        if e.response is not None:
            error_detail = f" (状态码: {e.response.status_code}, 内容: {e.response.text[:200]})"
        elif resp is not None:
            error_detail = f" (状态码: {resp.status_code}, 内容: {resp.text[:200]})"
        raise RuntimeError(f"API 请求失败: {e}{error_detail}") from e
    except json.JSONDecodeError as e:
        resp_text = resp.text if resp is not None else "<无响应>"
        raise RuntimeError(f"API 响应非 JSON: {e} (内容: {resp_text[:200]})") from e

# ==================== 验证码识别（来自文件一） ====================
def recognize_captcha(page: ChromiumPage, max_retries: int = 3) -> str:
    """识别验证码，失败时自动刷新重试"""
    ocr = ddddocr.DdddOcr(show_ad=False)
    for attempt in range(max_retries):
        img = find_element(
            page,
            '@id=kaptchaImage',
            '@src=/am/validate.code',
            lambda p: next((el for el in p.eles('tag:img', timeout=2)
                            if 'captcha' in (el.attr('src') or '').lower() or
                               'code' in (el.attr('src') or '').lower()), None)
        )
        if not img:
            raise RuntimeError("❌ 未找到验证码图片元素")

        CAPTCHA_IMG_DIR.mkdir(exist_ok=True)
        img.save(path=str(CAPTCHA_IMG_DIR), name='captcha.png')
        with open(CAPTCHA_IMG_PATH, 'rb') as f:
            image_bytes = f.read()
        result = ocr.classification(image_bytes)
        logger.info(f"识别到的验证码: {result}")

        if len(result) >= 4 and result.isalnum():
            return result

        logger.warning(f"验证码识别结果不合理（{result}），刷新重试...")
        try:
            img.click()  # 刷新验证码
        except Exception:
            pass
        time.sleep(1)

    raise RuntimeError("❌ 验证码识别失败，已达最大重试次数")

# ==================== 登录辅助函数（来自文件一） ====================
def _wait_for_login_redirect(page: ChromiumPage) -> Optional[str]:
    """等待跳转到 of 域并获取有效 token"""
    start_time = time.time()
    entered_target = False
    token = None

    while time.time() - start_time < TIMEOUT_PAGE_LOAD:
        current_url = page.url
        if 'of.swu.edu.cn' in current_url:
            if not entered_target:
                logger.info("已进入目标域，开始轮询 localStorage...")
                entered_target = True

            token = page.run_js('return localStorage.getItem("access_token");')
            if token:
                logger.info("从 localStorage 获取 token 成功，验证有效性...")
                try:
                    test_url = API_USER_URL
                    js_check = f'''
                        return fetch("{test_url}", {{
                            headers: {{"fighter-auth-token": "{token}"}}
                        }}).then(r => r.ok);
                    '''
                    ok = page.run_js(js_check)
                    if ok:
                        logger.info("localStorage 中的 token 有效")
                        return token
                    logger.warning("token 无效，继续等待...")
                    token = None
                except Exception as e:
                    logger.warning(f"验证 token 异常: {e}")
                    token = None
        else:
            if entered_target:
                entered_target = False

        elapsed = time.time() - start_time
        if int(elapsed) % 5 == 0:
            logger.debug(f"已等待 {elapsed:.0f}s，当前 URL: {current_url[:80]}...")
        time.sleep(0.2)

    return None

def _handle_iframe(page: ChromiumPage) -> None:
    """尝试切换 iframe（如有）"""
    iframes = page.eles('tag:iframe', timeout=3)
    if iframes:
        logger.debug(f"发现 {len(iframes)} 个 iframe，尝试切换")
        try:
            frame_method = getattr(page, 'to_frame', None) or getattr(page, 'switch_to_frame', None)
            if frame_method:
                frame_method(iframes[0])
        except Exception as e:
            logger.warning(f"切换 iframe 失败: {e}")

def _navigate_to_login(page: ChromiumPage) -> None:
    """导航到登录页面"""
    page.get(LOGIN_URL)
    logger.info(f"当前页面标题: {page.title}")

    unified_btn = page.ele('@src=img/unified_button.png', timeout=5)
    if unified_btn:
        unified_btn.click()
        logger.info("已点击统一认证按钮，等待跳转...")
        start_wait = time.time()
        while time.time() - start_wait < 8:
            time.sleep(0.5)
            if 'idm.swu.edu.cn' in page.url or 'Login' in page.url:
                logger.info(f"跳转成功，当前URL: {page.url[:100]}...")
                break
        else:
            logger.warning("跳转超时，尝试刷新页面...")
            page.refresh()
            time.sleep(3)
            if 'idm.swu.edu.cn' not in page.url and 'Login' not in page.url:
                logger.warning("刷新后仍未进入登录页，尝试直接访问基础登录页...")
                page.get(BASE_LOGIN_URL)
                time.sleep(2)
    else:
        logger.info("未找到统一认证按钮，直接访问基础登录页...")
        page.get(BASE_LOGIN_URL)
        time.sleep(2)

def _fill_login_form(page: ChromiumPage, username: str, password: str) -> str:
    """填写登录表单并返回识别出的验证码"""
    # 用户名
    username_input = find_input(
        page,
        [
            '@name=username',
            '@name=j_username',
            lambda p: p.eles('tag:input@type=text', timeout=3)[0] if p.eles('tag:input@type=text', timeout=3) else None
        ]
    )
    if not username_input:
        raise RuntimeError("❌ 未找到用户名输入框")
    username_input.clear().input(username)
    logger.info("已输入用户名")

    # 密码
    password_input = find_input(
        page,
        [
            '@name=password',
            '@name=j_password',
            lambda p: p.eles('tag:input@type=password', timeout=3)[0] if p.eles('tag:input@type=password', timeout=3) else None
        ]
    )
    if not password_input:
        raise RuntimeError("❌ 未找到密码输入框")
    password_input.clear().input(password)
    logger.info("已输入密码")

    # 验证码识别
    captcha_code = recognize_captcha(page)
    logger.info(f"最终识别验证码: {captcha_code}")

    # 验证码输入框
    captcha_input = find_input(
        page,
        [
            '@name=captcha',
            '@name=verificationCode',
            lambda p: p.eles('tag:input@type=text', timeout=3)[-1] if len(p.eles('tag:input@type=text', timeout=3)) > 1 else None,
            'xpath://input[@type="text"][position()>2]'
        ]
    )
    if not captcha_input:
        raise RuntimeError("❌ 未找到验证码输入框")

    captcha_input.clear()
    page.actions.click(captcha_input).wait(0.1)
    for ch in captcha_code:
        page.actions.type(ch).wait(0.05)
    # 触发事件
    page.run_js('''
        var el = arguments[0];
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new Event('blur', { bubbles: true }));
        el.dispatchEvent(new Event('keyup', { bubbles: true }));
        el.dispatchEvent(new Event('keydown', { bubbles: true }));
    ''', captcha_input)
    time.sleep(0.3)
    logger.info("已输入验证码")
    return captcha_code

def _click_login_button(page: ChromiumPage) -> None:
    """点击登录按钮"""
    login_btn = find_element(
        page,
        '@style=vertical-align: top;',
        '.btn.btn-default.blue',
        'tag:input@type=submit',
        'text=登录'
    )
    if not login_btn:
        raise RuntimeError("❌ 未找到登录按钮")
    page.actions.move_to(login_btn).click().wait(0.5)
    logger.info("已点击登录按钮")
    time.sleep(1)

    # 检查错误消息
    error_msgs = page.eles('.error, #err, .msg-error, .alert-danger', timeout=1)
    if error_msgs:
        raise RuntimeError(f"登录失败: {error_msgs[0].text}")

# ==================== 登录主函数（来自文件一） ====================
def login_and_get_token(username: str, password: str, headless: bool = False) -> str:
    """执行登录流程并返回有效 token"""
    with browser_page(headless) as page:
        for attempt in range(1, MAX_RETRIES + 1):
            logger.info(f"--- 第 {attempt} 次尝试登录 ---")
            try:
                _navigate_to_login(page)
                _handle_iframe(page)
                _fill_login_form(page, username, password)
                _click_login_button(page)
                time.sleep(0.5)

                # 转到 of 域等待 token
                page.get(LOGIN_URL)
                time.sleep(2)
                logger.info("等待登录成功后跳转...")
                token = _wait_for_login_redirect(page)
                if token:
                    remove_captcha_image()
                    return token

                raise RuntimeError("获取 token 超时或无效")
            except Exception as e:
                logger.error(f"第 {attempt} 次尝试失败: {e}")
                remove_captcha_image()
                if attempt == MAX_RETRIES:
                    raise
                logger.info("等待 2 秒后重试...")
                time.sleep(2)

        raise RuntimeError(f"登录失败，已重试 {MAX_RETRIES} 次。")

# ==================== 打卡辅助函数（来自文件一，供备用及文件二打卡使用） ====================
def get_transition_today(token: str) -> Dict:
    """获取今日打卡任务"""
    result = api_request('POST', API_TASK_URL, token, data={"pageNum": 1, "pageSize": 1})
    records = result.get("data", {}).get("records", [])
    return records[0] if records else {}

def get_student_id(token: str) -> str:
    """获取当前用户学号"""
    result = api_request('GET', API_USER_URL, token)
    return result["data"]["subject"]["username"]

# ==================== 打卡模块（来自文件二，全程浏览器 fetch） ====================
def checkin_with_page(page: ChromiumPage, token: str) -> Tuple[bool, str]:
    """
    通过浏览器 fetch 执行打卡（文件二方式，无随机时间）
    返回 (成功标志, 消息)
    """
    try:
        logger.info("导航到 of.swu.edu.cn 以建立同源环境...")
        page.get('https://of.swu.edu.cn')
        time.sleep(1)

        task = get_transition_today(token)
        if not task:
            return True, "今日无打卡任务"
        if task.get("qdzt") == "已签到":
            return True, "今日已签到，无需重复"

        student_id = get_student_id(token)
        logger.info(f"当前用户后三位: {student_id[-3:] if len(student_id) >= 3 else student_id}")

        formid = task["formId"]
        url = API_CHECKIN_URL
        params = {"formId": formid, "isSubmitProcess": False}
        query = "&".join(f"{k}={v}" for k, v in params.items())
        full_url = f"{url}?{query}"

        # 使用固定时间（文件二）
        payload = {
            "id": task["id"],
            "formId": formid,
            "tsrq": time.strftime("%Y-%m-%d"),
            "xh": student_id,
            "qdsj": CHECKIN_TIME_RANGE,
        }

        headers = {
            "fighter-auth-token": token,
            "Content-Type": "application/json;charset=UTF-8"
        }

        js_code = f'''
            return fetch("{full_url}", {{
                method: "POST",
                headers: {json.dumps(headers)},
                body: JSON.stringify({json.dumps(payload)})
            }})
            .then(response => response.json())
            .catch(error => ({{ error: error.message }}));
        '''
        result = page.run_js(js_code)

        if result and result.get("error"):
            return False, f"打卡提交异常: {result['error']}"
        if result.get("code") == 200 and result.get("data"):
            return True, "打卡成功！"
        else:
            return False, f"打卡失败: {result.get('msg', '未知错误')}"
    except Exception as e:
        logger.exception("浏览器打卡过程中发生异常")
        return False, f"打卡过程中异常: {e}"

# ==================== 主程序 ====================
def main():
    parser = argparse.ArgumentParser(description='西南大学自动打卡（整合版）')
    parser.add_argument('--no-headless', action='store_true', help='禁用无头模式')
    args = parser.parse_args()
    headless_mode = not args.no_headless

    # 从环境变量读取凭证
    username = os.environ.get('SWU_USERNAME')
    password = os.environ.get('SWU_PASSWORD')
    if not username or not password:
        logger.error("请设置环境变量 SWU_USERNAME 和 SWU_PASSWORD")
        sys.exit(1)

    # 可选手动 token
    token = os.environ.get('SWU_TOKEN', '').strip()

    if not token:
        logger.info("未指定 token，将自动登录获取...")
        try:
            token = login_and_get_token(username, password, headless=headless_mode)
            logger.info(f"获取到的 token: {token[:10]}...")
        except Exception as e:
            logger.error(f"自动登录失败: {e}")
            sys.exit(1)
    else:
        logger.info(f"使用环境变量中的 token: {token[:10]}...")
        try:
            student_id = get_student_id(token)
            logger.info(f"Token 有效，当前后三位: {student_id[-3:] if len(student_id) >= 3 else student_id}")
        except Exception as e:
            logger.error(f"Token 无效或已过期: {e}")
            sys.exit(1)

    # 执行打卡
    logger.info("--- 开始打卡 ---")
    try:
        with browser_page(headless_mode) as page:
            success, message = checkin_with_page(page, token)
    except Exception as e:
        logger.warning(f"浏览器打卡过程抛出异常: {e}")
        success, message = False, f"浏览器异常: {e}"

    if success:
        logger.info(f"✅ 打卡流程完成：{message}")
        remove_captcha_image()
        sys.exit(0)
    else:
        print("打卡失败")

if __name__ == "__main__":
    main()
