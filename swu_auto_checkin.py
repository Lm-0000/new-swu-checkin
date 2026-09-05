#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import json
import argparse
import random
import shutil
from typing import Tuple, Any, Dict, Optional, cast

import requests
import ddddocr
from DrissionPage import ChromiumPage, ChromiumOptions

# ==================== 配置区 ====================
MANUAL_TOKEN = ""
CHECKIN_TIME_RANGE = ["21:00", "23:30"]
MAX_RETRIES = 3

# ==================== 工具函数 ====================
def get_chrome_path() -> str:
    """获取 Chrome/Chromium 可执行文件路径"""
    chrome_path = os.environ.get('CHROME_PATH')
    if chrome_path and os.path.isfile(chrome_path):
        return chrome_path

    linux_paths = [
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable',
        '/usr/bin/chromium-browser',
        '/usr/bin/chromium',
        '/opt/google/chrome/chrome',
    ]
    for path in linux_paths:
        if os.path.isfile(path):
            return path

    win_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for path in win_paths:
        if os.path.isfile(path):
            return path

    # 显式忽略 PathLike 类型警告（Python <3.12 上 shutil.which 不接受 PathLike）
    chrome_cmd = shutil.which('google-chrome')  # type: ignore[arg-type]
    if not chrome_cmd:
        chrome_cmd = shutil.which('chrome')     # type: ignore[arg-type]
    if chrome_cmd:
        return chrome_cmd

    raise RuntimeError("❌ 未找到 Chrome 浏览器")

def remove_captcha_image() -> None:
    """清理验证码图片缓存"""
    file_path = 'images/captcha.png'
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError:  # 忽略删除错误
            pass
        try:
            os.rmdir('images')
        except OSError:
            pass

def generate_random_time_range(base_start: str, base_end: str) -> Tuple[str, str]:
    """生成随机时间（精确到秒）"""
    def randomize_time(time_str: str) -> str:
        h, m = map(int, time_str.split(':'))
        s = random.randint(0, 59)
        return f"{h:02d}:{m:02d}:{s:02d}"
    return randomize_time(base_start), randomize_time(base_end)

def create_browser_page(chrome_path: str, headless: bool = False) -> ChromiumPage:
    """创建浏览器页面对象，处理无头模式"""
    is_ci = os.environ.get('GITHUB_ACTIONS') == 'true'
    use_headless = headless or is_ci

    co = ChromiumOptions()
    # set_paths 类型存根不完整，忽略属性/参数类型警告
    co.set_paths(browser_path=chrome_path)  # type: ignore[attr-defined, call-overload]

    co.set_argument('--window-size=1920,1080')
    co.set_argument('--no-sandbox')
    co.set_argument('--disable-gpu')
    co.set_argument('--disable-dev-shm-usage')
    co.set_argument('--disable-cache')
    co.set_argument('--disable-application-cache')

    if use_headless:
        co.set_argument('--headless=new')
        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    return ChromiumPage(co)

def recognize_captcha(page: ChromiumPage, max_retries: int = 3) -> str:
    """识别验证码，支持重试和刷新"""
    ocr = ddddocr.DdddOcr(show_ad=False)
    for attempt in range(max_retries):
        img = page.ele('@id=kaptchaImage', timeout=3) or page.ele('@src=/am/validate.code', timeout=3)
        if not img:
            for img_tag in page.eles('tag:img', timeout=2):
                src = img_tag.attr('src') or ''
                if 'captcha' in src.lower() or 'code' in src.lower():
                    img = img_tag
                    break
        if not img:
            raise RuntimeError("❌ 未找到验证码图片元素")

        os.makedirs('images', exist_ok=True)
        img.save(path='images', name='captcha.png')

        with open('images/captcha.png', 'rb') as f:
            image_bytes = f.read()
        result = ocr.classification(image_bytes)
        print(f"识别到的验证码: {result}")

        if len(result) >= 4 and result.isalnum():
            return result

        print(f"⚠️ 验证码识别结果不合理（{result}），刷新重试...")
        try:
            img.click()
        except Exception:  # 点击失败忽略，继续循环  # noqa: E722
            pass
        time.sleep(1)

    raise RuntimeError("❌ 验证码识别失败")

def get_task_and_student_id(token: str) -> Tuple[Dict[str, Any], str]:
    """获取今日打卡任务和学号"""
    headers = {"fighter-auth-token": token}

    url_task = "https://of.swu.edu.cn/gateway/fighter-baida/api/cqtj/getTransitionByToday"
    data = {"pageNum": 1, "pageSize": 1}
    try:
        resp = requests.post(url_task, headers=headers, data=data, timeout=10)
        resp.raise_for_status()
        resp_data = resp.json()
        records = resp_data.get("data", {}).get("records", [])
        task = records[0] if records else {}
    except requests.RequestException as e:
        raise RuntimeError(f"查询任务网络失败: {e}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"任务数据解析失败: {e}") from e

    url_user = "https://of.swu.edu.cn/gateway/fighter-middle/api/auth/user?appType=fighter-portal"
    try:
        resp = requests.get(url_user, headers=headers, timeout=10)
        resp.raise_for_status()
        student_id = resp.json()["data"]["subject"]["username"]
    except requests.RequestException as e:
        raise RuntimeError(f"获取学号网络失败: {e}") from e
    except (json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f"学号数据解析失败: {e}") from e

    return task, student_id

def build_checkin_payload(task: Dict[str, Any], student_id: str) -> Dict[str, Any]:
    """构建打卡提交数据"""
    formid = task["formId"]
    record_id = task["id"]
    start_time_str, end_time_str = generate_random_time_range(
        CHECKIN_TIME_RANGE[0], CHECKIN_TIME_RANGE[1]
    )
    return {
        "id": record_id,
        "formId": formid,
        "tsrq": time.strftime("%Y-%m-%d"),
        "xh": student_id,
        "qdsj": [start_time_str, end_time_str],
    }

# ==================== 登录模块 ====================
def login_and_get_page(
    username: str,
    password: str,
    headless: bool = False,
    max_retries: int = MAX_RETRIES
) -> Tuple[ChromiumPage, str]:
    """自动登录并返回 page 对象和 token"""
    chrome_path = get_chrome_path()
    print(f"✅ 使用 Chrome: {chrome_path}")

    for attempt in range(1, max_retries + 1):
        print(f"\n--- 第 {attempt} 次尝试登录 ---")
        page = None
        try:
            page = create_browser_page(chrome_path, headless)
            print("✅ 浏览器启动成功")
        except Exception as e:  # 启动失败，尝试切换模式  # noqa: E722
            print(f"❌ 启动失败: {e}")
            if headless or os.environ.get('GITHUB_ACTIONS') == 'true':
                try:
                    page = create_browser_page(chrome_path, False)
                    print("✅ 已切换到非无头模式")
                except Exception as e2:  # noqa: E722
                    print(f"❌ 非无头模式也失败: {e2}")
                    raise RuntimeError("浏览器无法启动") from e2
            else:
                raise RuntimeError("浏览器启动失败") from e

        try:
            login_url = (
                'https://of.swu.edu.cn/cas/oauth/login/SWU_CAS2_FEDERAL'
                '?service=https%3A%2F%2Fof.swu.edu.cn%2Fgateway%2Ffighter-middle%2Fapi%2Fintegrate%2Fuaap%2Fcas%2Fresolve-cas-return'
                '%3Fnext%3Dhttps%253A%252F%252Fof.swu.edu.cn%252F%2523%252FcasLogin%253Ffrom%253D%25252FappCenter'
            )
            page.get(login_url)
            print(f"当前页面标题: {page.title}")
            print(f"当前URL: {page.url}")

            unified_btn = page.ele('@src=img/unified_button.png', timeout=5)
            if unified_btn:
                unified_btn.click()
                print("已点击统一认证按钮，等待跳转...")
                wait_start = time.time()
                while time.time() - wait_start < 8:
                    time.sleep(0.5)
                    current_url = page.url
                    if 'idm.swu.edu.cn' in current_url or 'Login' in current_url:
                        print(f"✅ 跳转成功，当前URL: {current_url[:100]}...")
                        break
                else:
                    print("⚠️ 跳转超时，尝试刷新页面...")
                    page.refresh()
                    time.sleep(3)
                    if 'idm.swu.edu.cn' not in page.url and 'Login' not in page.url:
                        print("⚠️ 刷新后仍未进入登录页，尝试直接访问基础登录页...")
                        page.get('https://idm.swu.edu.cn/am/UI/Login')
                        time.sleep(2)
            else:
                print("未找到统一认证按钮，直接访问基础登录页...")
                page.get('https://idm.swu.edu.cn/am/UI/Login')
                time.sleep(2)

            print(f"当前登录页标题: {page.title}")
            print(f"当前登录页URL: {page.url}")

            # 切换 iframe（兼容版本）
            iframes = page.eles('tag:iframe', timeout=3)
            if iframes:
                print(f"发现 {len(iframes)} 个 iframe，尝试切换到第一个")
                try:
                    frame_method = getattr(page, 'to_frame', None) or getattr(page, 'switch_to_frame', None)
                    if frame_method:
                        frame_method(iframes[0])
                    else:
                        print("⚠️ 未找到 iframe 切换方法")
                except Exception as e:  # noqa: E722
                    print(f"⚠️ 切换 iframe 失败: {e}")

            # 用户名
            username_input = (
                page.ele('@name=username', timeout=3) or
                page.ele('@name=j_username', timeout=3)
            )
            if not username_input:
                inputs = page.eles('tag:input@type=text', timeout=3)
                if inputs:
                    username_input = inputs[0]
            if not username_input:
                raise RuntimeError("❌ 未找到用户名输入框")
            username_input.clear().input(username)
            print("✅ 已输入用户名")

            # 密码
            password_input = (
                page.ele('@name=password', timeout=3) or
                page.ele('@name=j_password', timeout=3)
            )
            if not password_input:
                inputs = page.eles('tag:input@type=password', timeout=3)
                if inputs:
                    password_input = inputs[0]
            if not password_input:
                raise RuntimeError("❌ 未找到密码输入框")
            password_input.clear().input(password)
            print("✅ 已输入密码")

            # 验证码
            captcha_code = recognize_captcha(page)
            print(f"最终识别验证码: {captcha_code}")

            captcha_input = (
                page.ele('@name=captcha', timeout=3) or
                page.ele('@name=verificationCode', timeout=3)
            )
            if not captcha_input:
                inputs = page.eles('tag:input@type=text', timeout=3)
                if inputs:
                    captcha_input = inputs[-1] if len(inputs) > 1 else inputs[0]
            if not captcha_input:
                captcha_input = page.ele('xpath://input[@type="text"][position()>2]', timeout=3)
            if not captcha_input:
                raise RuntimeError("❌ 未找到验证码输入框")

            captcha_input.clear()
            page.actions.click(captcha_input).wait(0.1)
            for ch in captcha_code:
                page.actions.type(ch).wait(0.05)
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

            login_btn = (
                page.ele('@style=vertical-align: top;', timeout=3) or
                page.ele('.btn.btn-default.blue', timeout=3) or
                page.ele('tag:input@type=submit', timeout=3) or
                page.ele('text=登录', timeout=3)
            )
            if not login_btn:
                raise RuntimeError("❌ 未找到登录按钮")

            page.actions.move_to(login_btn).click().wait(0.5)
            print("✅ 已点击登录按钮")
            time.sleep(1)

            error_msgs = page.eles('.error, #err, .msg-error, .alert-danger', timeout=1)
            if error_msgs:
                for e_msg in error_msgs:
                    print(f"⚠️ 错误信息: {e_msg.text}")
                raise RuntimeError(f"登录失败: {error_msgs[0].text}")

            # token 提取
            time.sleep(0.5)
            page.get(login_url)
            time.sleep(2)
            print("等待登录成功后跳转...")
            start_time = time.time()
            timeout_sec = 20
            entered_target = False
            token = None

            while time.time() - start_time < timeout_sec:
                current_url = page.url

                if 'of.swu.edu.cn' in current_url:
                    if not entered_target:
                        print("✅ 已进入目标域，开始轮询 localStorage...")
                        entered_target = True

                    token = page.run_js('return localStorage.getItem("access_token");')
                    if token:
                        print("✅ 从 localStorage 获取 token 成功，尝试验证有效性...")
                        try:
                            test_url = "https://of.swu.edu.cn/gateway/fighter-middle/api/auth/user?appType=fighter-portal"
                            js_check = f'''
                                return fetch("{test_url}", {{
                                    headers: {{"fighter-auth-token": "{token}"}}
                                }}).then(r => r.ok);
                            '''
                            ok = page.run_js(js_check)
                            if ok:
                                print("✅ localStorage 中的 token 有效")
                                remove_captcha_image()
                                return page, cast(str, token)
                            else:
                                print("⚠️ localStorage 中的 token 无效，继续等待...")
                                token = None
                        except Exception as e:  # noqa: E722
                            print(f"⚠️ 验证 token 时发生异常: {e}")
                            token = None
                else:
                    if entered_target:
                        entered_target = False

                elapsed = time.time() - start_time
                if int(elapsed) % 5 == 0:
                    print(f"⏳ 已等待 {elapsed:.0f}s，当前 URL: {current_url[:80]}...")

                time.sleep(0.2)

            raise RuntimeError("获取 token 超时（20s）")

        except Exception as e:  # 整体捕获，用于重试  # noqa: E722
            print(f"第 {attempt} 次尝试失败: {e}")
            remove_captcha_image()
            if page:
                try:
                    page.quit()
                except Exception:  # noqa: E722
                    pass
            if attempt == max_retries:
                raise
            print("等待 2 秒后重试...")
            time.sleep(2)

    raise RuntimeError(f"登录失败，已重试 {max_retries} 次。")

# ==================== 打卡模块 ====================
def _prepare_checkin_data(token: str) -> Tuple[Dict[str, Any], str, Optional[Dict[str, Any]], bool]:
    """
    准备打卡数据
    返回 (task, student_id, payload_or_None, skip)
    skip 为 True 表示无需打卡（无任务或已签到），此时 payload 为 None
    """
    task, student_id = get_task_and_student_id(token)
    if not task:
        return {}, student_id, None, True
    if task.get("qdzt") == "已签到":
        return task, student_id, None, True
    payload = build_checkin_payload(task, student_id)
    return task, student_id, payload, False

def do_checkin_with_page(page: ChromiumPage, token: str) -> Tuple[bool, str, int]:
    """使用浏览器页面对象进行打卡（通过 fetch）"""
    try:
        task, _, payload, skip = _prepare_checkin_data(token)
        if skip:
            if not task:
                return True, "今日无打卡任务", 10
            return True, "今日已签到，无需重复", 0

        formid = task["formId"]
        url = "https://of.swu.edu.cn/gateway/fighter-baida/api/form-instance/save"
        headers = {"fighter-auth-token": token, "Content-Type": "application/json;charset=UTF-8"}

        js_code = f'''
            return fetch("{url}?formId={formid}&isSubmitProcess=false", {{
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
        else:
            return False, f"打卡失败: {result.get('msg', '未知错误')}", 20
    except Exception as e:  # noqa: E722
        return False, f"打卡过程中异常: {e}", 20

def do_checkin_requests(token: str) -> Tuple[bool, str, int]:
    """使用 requests 直接提交打卡"""
    try:
        task, _, payload, skip = _prepare_checkin_data(token)
        if skip:
            if not task:
                return True, "今日无打卡任务", 10
            return True, "今日已签到，无需重复", 0

        formid = task["formId"]
        url = "https://of.swu.edu.cn/gateway/fighter-baida/api/form-instance/save"
        headers = {"fighter-auth-token": token, "Content-Type": "application/json;charset=UTF-8"}

        resp = requests.post(
            url,
            headers=headers,
            params={"formId": formid, "isSubmitProcess": False},
            data=json.dumps(payload),
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 200 and data.get("data"):
            return True, "打卡成功！", 0
        else:
            return False, f"打卡失败: {data.get('msg', '未知错误')}", 20
    except requests.RequestException as e:
        return False, f"网络请求异常: {e}", 20
    except json.JSONDecodeError as e:
        return False, f"响应解析异常: {e}", 20
    except Exception as e:  # noqa: E722
        return False, f"未知异常: {e}", 20

# ==================== 主程序 ====================
def main():
    parser = argparse.ArgumentParser(description='西南大学自动打卡（全程浏览器）')
    parser.add_argument('--no-headless', action='store_true', help='禁用无头模式')
    args = parser.parse_args()
    headless_mode = not args.no_headless

    username = os.environ.get('SWU_USERNAME')
    password = os.environ.get('SWU_PASSWORD')
    if not username or not password:
        print("❌ 请设置环境变量 SWU_USERNAME 和 SWU_PASSWORD")
        sys.exit(1)

    token = os.environ.get('SWU_TOKEN', '').strip() or MANUAL_TOKEN.strip()
    page: Optional[ChromiumPage] = None

    if not token:
        print("未指定手动 token，将自动登录获取...")
        try:
            page, token = login_and_get_page(username, password, headless=headless_mode)
            print(f"\n✅ 获取到的 token: {token[:10]}...")
        except Exception as e:  # noqa: E722
            print(f"❌ 自动登录失败: {e}")
            sys.exit(1)
    else:
        print(f"使用手动指定的 token: {token[:10]}...")
        try:
            _, student_id = get_task_and_student_id(token)
            print(f"Token 有效，当前学号: {student_id}")
        except Exception as e:  # noqa: E722
            print(f"❌ Token 无效或已过期: {e}")
            sys.exit(1)

    print("\n--- 开始打卡 ---")
    if page is not None:
        success, reason, exit_code = do_checkin_with_page(page, token)
    else:
        success, reason, exit_code = do_checkin_requests(token)

    if page is not None:
        try:
            page.quit()
            print("✅ 浏览器已关闭")
        except Exception:  # noqa: E722
            pass

    remove_captcha_image()

    if success:
        print(f"✅ 打卡流程完成：{reason}")
        sys.exit(0)
    else:
        print(f"❌ 打卡失败：{reason}")
        sys.exit(exit_code)

if __name__ == "__main__":
    main()
