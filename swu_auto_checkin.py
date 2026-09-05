#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
西南大学自动打卡脚本（整合版）
- 登录模块（验证码重试、清晰流程）
- 打卡模块（使用浏览器 fetch，UA 指纹一致）
- 支持无头模式、手动 Token 回退
- 重构版本 v5：所有静态检查警告已消除
"""

import os
import sys
import time
import json
import argparse
import random
import shutil
from typing import Tuple, Generator, Optional, Any
from contextlib import contextmanager

import requests
import ddddocr  # 验证码识别
from DrissionPage import ChromiumPage, ChromiumOptions

# ==================== 配置常量 ====================
MANUAL_TOKEN = ""
CHECKIN_TIME_RANGE = ["21:00", "23:30"]
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
CAPTCHA_IMG_DIR = 'images'
CAPTCHA_IMG_PATH = os.path.join(CAPTCHA_IMG_DIR, 'captcha.png')
TIMEOUT_PAGE_LOAD = 20
TIMEOUT_API = 10

# ==================== 工具函数 ====================
def get_chrome_path() -> str:
    """获取 Chrome/Chromium 可执行文件路径"""
    env_path = os.environ.get('CHROME_PATH')
    if env_path and os.path.isfile(env_path):
        return str(env_path)

    # 合并所有可能的路径，减少重复
    possible_paths = [
        '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable',
        '/usr/bin/chromium-browser', '/usr/bin/chromium',
        '/opt/google/chrome/chrome',
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for path in possible_paths:
        if os.path.isfile(path):
            return path

    # 通过 shutil.which 查找（显式字符串，避免 PathLike 警告）
    for cmd in ('google-chrome', 'chrome'):
        chrome_cmd = shutil.which(cmd)
        if chrome_cmd:
            return str(chrome_cmd)

    raise RuntimeError("❌ 未找到 Chrome 浏览器")


def remove_captcha_image() -> None:
    """清理验证码图片缓存"""
    if os.path.exists(CAPTCHA_IMG_PATH):
        try:
            os.remove(CAPTCHA_IMG_PATH)
        except OSError:
            pass
        try:
            os.rmdir(CAPTCHA_IMG_DIR)
        except OSError:
            pass


def generate_random_time_range(base_start: str, base_end: str) -> Tuple[str, str]:
    """生成随机时间（精确到秒）"""
    def randomize_time(time_str: str) -> str:
        h, m = map(int, time_str.split(':'))
        s = random.randint(0, 59)
        return f"{h:02d}:{m:02d}:{s:02d}"
    return randomize_time(base_start), randomize_time(base_end)


@contextmanager
def browser_page(headless: bool = False) -> Generator[ChromiumPage, None, None]:
    """上下文管理器，自动创建和清理浏览器页面"""
    chrome_path = get_chrome_path()
    is_ci = os.environ.get('GITHUB_ACTIONS') == 'true'
    use_headless = headless or is_ci

    co = ChromiumOptions()
    # 第三方库类型定义缺失，忽略类型检查
    co.set_paths(browser_path=chrome_path)  # type: ignore[attr-defined]
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
        except Exception:  # 资源清理，忽略所有异常
            pass


def find_element(page: ChromiumPage, *selectors: Any, timeout: int = 3):
    """按顺序尝试多个选择器，返回第一个匹配的元素"""
    for sel in selectors:
        if callable(sel):
            el = sel(page)
        else:
            el = page.ele(sel, timeout=timeout)
        if el:
            return el
    return None


def api_request(method: str, url: str, token: str,
                params: Optional[dict] = None,
                data: Optional[dict] = None,
                json_data: Optional[dict] = None) -> dict:
    """统一 API 请求"""
    headers = {"fighter-auth-token": token}
    if json_data is not None:
        headers["Content-Type"] = "application/json;charset=UTF-8"
    try:
        resp = requests.request(
            method, url, headers=headers, params=params,
            data=data, json=json_data, timeout=TIMEOUT_API
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise RuntimeError(f"API 请求失败: {e}") from e


# ==================== 验证码识别 ====================
def recognize_captcha(page: ChromiumPage, max_retries: int = 3) -> str:
    """识别验证码，支持重试和刷新"""
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

        os.makedirs(CAPTCHA_IMG_DIR, exist_ok=True)
        img.save(path=CAPTCHA_IMG_DIR, name='captcha.png')

        with open(CAPTCHA_IMG_PATH, 'rb') as f:
            image_bytes = f.read()
        result = ocr.classification(image_bytes)
        print(f"识别到的验证码: {result}")

        if len(result) >= 4 and result.isalnum():
            return result

        print(f"⚠️ 验证码识别结果不合理（{result}），刷新重试...")
        try:
            img.click()
        except Exception:   # 点击刷新可能失败，忽略
            pass
        time.sleep(1)

    raise RuntimeError("❌ 验证码识别失败")


# ==================== 登录辅助函数 ====================
def _wait_for_login_redirect(page: ChromiumPage) -> Optional[str]:
    """等待登录成功，从 localStorage 提取 token"""
    start_time = time.time()
    entered_target = False
    token = None

    while time.time() - start_time < TIMEOUT_PAGE_LOAD:
        current_url = page.url
        if 'of.swu.edu.cn' in current_url:
            if not entered_target:
                print("✅ 已进入目标域，开始轮询 localStorage...")
                entered_target = True
            token = page.run_js('return localStorage.getItem("access_token");')
            if token:
                print("✅ 从 localStorage 获取 token 成功，验证有效性...")
                try:
                    test_url = API_USER_URL
                    js_check = f'''
                        return fetch("{test_url}", {{
                            headers: {{"fighter-auth-token": "{token}"}}
                        }}).then(r => r.ok);
                    '''
                    ok = page.run_js(js_check)
                    if ok:
                        print("✅ localStorage 中的 token 有效")
                        return token
                    print("⚠️ token 无效，继续等待...")
                    token = None
                except Exception as e:
                    print(f"⚠️ 验证 token 异常: {e}")
                    token = None
        else:
            if entered_target:
                entered_target = False

        elapsed = time.time() - start_time
        if int(elapsed) % 5 == 0:
            print(f"⏳ 已等待 {elapsed:.0f}s，当前 URL: {current_url[:80]}...")
        time.sleep(0.2)

    return None


def _handle_iframe(page: ChromiumPage) -> None:
    """切换 iframe（若存在）"""
    iframes = page.eles('tag:iframe', timeout=3)
    if iframes:
        print(f"发现 {len(iframes)} 个 iframe，尝试切换")
        try:
            frame_method = getattr(page, 'to_frame', None) or getattr(page, 'switch_to_frame', None)
            if frame_method:
                frame_method(iframes[0])
        except Exception as e:
            print(f"⚠️ 切换 iframe 失败: {e}")


def _navigate_to_login(page: ChromiumPage) -> None:
    """导航到登录页，处理统一认证跳转"""
    page.get(LOGIN_URL)
    print(f"当前页面标题: {page.title}")

    unified_btn = page.ele('@src=img/unified_button.png', timeout=5)
    if unified_btn:
        unified_btn.click()
        print("已点击统一认证按钮，等待跳转...")
        start_wait = time.time()
        while time.time() - start_wait < 8:
            time.sleep(0.5)
            if 'idm.swu.edu.cn' in page.url or 'Login' in page.url:
                print(f"✅ 跳转成功，当前URL: {page.url[:100]}...")
                break
        else:
            print("⚠️ 跳转超时，尝试刷新页面...")
            page.refresh()
            time.sleep(3)
            if 'idm.swu.edu.cn' not in page.url and 'Login' not in page.url:
                print("⚠️ 刷新后仍未进入登录页，尝试直接访问基础登录页...")
                page.get(BASE_LOGIN_URL)
                time.sleep(2)
    else:
        print("未找到统一认证按钮，直接访问基础登录页...")
        page.get(BASE_LOGIN_URL)
        time.sleep(2)


def _fill_login_form(page: ChromiumPage, username: str, password: str) -> str:
    """
    填写登录表单，返回识别出的验证码
    """
    # 用户名
    username_input = find_element(
        page,
        '@name=username',
        '@name=j_username',
        lambda p: p.eles('tag:input@type=text', timeout=3)[0] if p.eles('tag:input@type=text', timeout=3) else None
    )
    if not username_input:
        raise RuntimeError("❌ 未找到用户名输入框")
    username_input.clear().input(username)
    print("✅ 已输入用户名")

    # 密码
    password_input = find_element(
        page,
        '@name=password',
        '@name=j_password',
        lambda p: p.eles('tag:input@type=password', timeout=3)[0] if p.eles('tag:input@type=password', timeout=3) else None
    )
    if not password_input:
        raise RuntimeError("❌ 未找到密码输入框")
    password_input.clear().input(password)
    print("✅ 已输入密码")

    # 验证码
    captcha_code = recognize_captcha(page)
    print(f"最终识别验证码: {captcha_code}")

    captcha_input = find_element(
        page,
        '@name=captcha',
        '@name=verificationCode',
        lambda p: p.eles('tag:input@type=text', timeout=3)[-1] if len(p.eles('tag:input@type=text', timeout=3)) > 1 else None,
        'xpath://input[@type="text"][position()>2]'
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
    print("✅ 已输入验证码")
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
    print("✅ 已点击登录按钮")
    time.sleep(1)

    error_msgs = page.eles('.error, #err, .msg-error, .alert-danger', timeout=1)
    if error_msgs:
        raise RuntimeError(f"登录失败: {error_msgs[0].text}")


# ==================== 登录主函数 ====================
def login_and_get_token(username: str, password: str, headless: bool = False) -> str:
    """自动登录并返回 token"""
    with browser_page(headless) as page:
        for attempt in range(1, MAX_RETRIES + 1):
            print(f"\n--- 第 {attempt} 次尝试登录 ---")
            try:
                _navigate_to_login(page)
                _handle_iframe(page)
                _fill_login_form(page, username, password)
                _click_login_button(page)

                # 等待 token
                time.sleep(0.5)
                page.get(LOGIN_URL)
                time.sleep(2)
                print("等待登录成功后跳转...")

                token = _wait_for_login_redirect(page)
                if token:
                    remove_captcha_image()
                    return token
                raise RuntimeError("获取 token 超时或无效")

            except Exception as e:
                print(f"第 {attempt} 次尝试失败: {e}")
                remove_captcha_image()
                if attempt == MAX_RETRIES:
                    raise
                print("等待 2 秒后重试...")
                time.sleep(2)

        raise RuntimeError(f"登录失败，已重试 {MAX_RETRIES} 次。")


# ==================== 打卡模块 ====================
def get_transition_today(token: str) -> dict:
    """获取今日任务"""
    result = api_request('POST', API_TASK_URL, token, data={"pageNum": 1, "pageSize": 1})
    records = result.get("data", {}).get("records", [])
    return records[0] if records else {}


def get_student_id(token: str) -> str:
    """获取学号"""
    result = api_request('GET', API_USER_URL, token)
    return result["data"]["subject"]["username"]


def build_checkin_payload(task: dict, student_id: str) -> dict:
    """构造打卡 payload"""
    start_time_str, end_time_str = generate_random_time_range(
        CHECKIN_TIME_RANGE[0], CHECKIN_TIME_RANGE[1]
    )
    return {
        "id": task["id"],
        "formId": task["formId"],
        "tsrq": time.strftime("%Y-%m-%d"),
        "xh": student_id,
        "qdsj": [start_time_str, end_time_str],
    }


def _checkin_common(token: str) -> Tuple[dict, str, bool]:
    """
    获取任务和学号，返回 (task, student_id, is_already_checked)
    """
    task = get_transition_today(token)
    if not task:
        return {}, "", True   # 无任务，无需打卡
    if task.get("qdzt") == "已签到":
        return task, "", True  # 已签到
    student_id = get_student_id(token)
    print(f"当前用户学号: {student_id}")
    return task, student_id, False


def checkin_with_page(page: ChromiumPage, token: str) -> Tuple[bool, str, int]:
    """浏览器打卡"""
    try:
        task, student_id, done = _checkin_common(token)
        if done:
            if not task:
                return True, "今日无打卡任务", 10
            return True, "今日已签到，无需重复", 0

        payload = build_checkin_payload(task, student_id)
        headers = {
            "fighter-auth-token": token,
            "Content-Type": "application/json;charset=UTF-8"
        }

        js_code = f'''
            return fetch("{API_CHECKIN_URL}?formId={task['formId']}&isSubmitProcess=false", {{
                method: "POST",
                headers: {json.dumps(headers)},
                body: JSON.stringify({json.dumps(payload)})
            }})
            .then(response => response.json())
            .catch(error => ({{ error: error.message }}));
        '''
        result = page.run_js(js_code)
        if result and result.get("error"):
            return False, f"打卡提交异常: {result['error']}", 20

        if result.get("code") == 200 and result.get("data"):
            return True, "打卡成功！", 0
        return False, f"打卡失败: {result.get('msg', '未知错误')}", 20

    except Exception as e:
        return False, f"打卡过程中异常: {e}", 20


def checkin_with_requests(token: str) -> Tuple[bool, str, int]:
    """requests 备用打卡"""
    try:
        task, student_id, done = _checkin_common(token)
        if done:
            if not task:
                return True, "今日无打卡任务", 10
            return True, "今日已签到，无需重复", 0

        payload = build_checkin_payload(task, student_id)
        params = {"formId": task["formId"], "isSubmitProcess": False}
        result = api_request('POST', API_CHECKIN_URL, token, params=params, json_data=payload)
        if result.get("code") == 200 and result.get("data"):
            return True, "打卡成功！", 0
        return False, f"打卡失败: {result.get('msg', '未知错误')}", 20
    except Exception as e:
        return False, f"异常: {e}", 20


# ==================== 主程序 ====================
def main():
    parser = argparse.ArgumentParser(description='西南大学自动打卡（整合版）')
    parser.add_argument('--no-headless', action='store_true', help='禁用无头模式')
    args = parser.parse_args()
    headless_mode = not args.no_headless

    username = os.environ.get('SWU_USERNAME')
    password = os.environ.get('SWU_PASSWORD')
    if not username or not password:
        print("❌ 请设置环境变量 SWU_USERNAME 和 SWU_PASSWORD")
        sys.exit(1)

    token: Optional[str] = os.environ.get('SWU_TOKEN', '').strip() or MANUAL_TOKEN.strip()

    if not token:
        print("未指定手动 token，将自动登录获取...")
        try:
            token = login_and_get_token(username, password, headless=headless_mode)
            print(f"\n✅ 获取到的 token: {token[:10]}...")
        except Exception as e:
            print(f"❌ 自动登录失败: {e}")
            sys.exit(1)
    else:
        print(f"使用手动指定的 token: {token[:10]}...")
        try:
            student_id = get_student_id(token)
            print(f"Token 有效，当前学号: {student_id}")
        except Exception as e:
            print(f"❌ Token 无效或已过期: {e}")
            sys.exit(1)

    # 确保 token 非空
    assert token is not None

    print("\n--- 开始打卡 ---")
    use_browser = True
    try:
        with browser_page(headless_mode) as page:
            success, reason, exit_code = checkin_with_page(page, token)
    except Exception as e:
        print(f"⚠️ 浏览器打卡失败，切换到 requests 方式: {e}")
        use_browser = False

    if not use_browser:
        success, reason, exit_code = checkin_with_requests(token)

    remove_captcha_image()

    if success:
        print(f"✅ 打卡流程完成：{reason}")
        sys.exit(0)
    print(f"❌ 打卡失败：{reason}")
    sys.exit(exit_code or 1)


if __name__ == "__main__":
    main()
