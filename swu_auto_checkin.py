#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
西南大学自动打卡脚本（全程浏览器版）
- 登录、获取 token、提交打卡均在同一浏览器会话中完成，UA/TLS 指纹全程一致
- 支持 GitHub Actions 无头模式
- 每次运行自动清除浏览器数据，保证环境干净
- 登录交互代码完全保留原样
"""

import os
import sys
import time
import json
import argparse
import subprocess
import socket
import shutil
import requests
import ddddocr
from typing import Optional, Tuple
from DrissionPage import ChromiumPage, ChromiumOptions

# ==================== 配置区 ====================
MANUAL_TOKEN = ""                     # 留空则自动登录
CHECKIN_TIME_RANGE = ["21:00", "23:30"]

# ==================== 工具函数 ====================
def get_chrome_path() -> str:
    """查找系统中 Chrome/Chromium 的可执行路径"""
    chrome_path = os.environ.get('CHROME_PATH')
    if chrome_path and os.path.isfile(chrome_path):
        return chrome_path
    for path in [
        '/usr/bin/google-chrome', '/usr/bin/chromium-browser', '/usr/bin/chromium',
        '/opt/google/chrome/chrome',
    ]:
        if os.path.isfile(path):
            return path
    for path in [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]:
        if os.path.isfile(path):
            return path
    try:
        result = subprocess.run(['which', 'google-chrome'], capture_output=True, text=True)
        if result.returncode == 0 and os.path.isfile(result.stdout.strip()):
            return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):  # 命令执行异常可忽略
        pass
    raise Exception("❌ 未找到 Chrome 浏览器")

def get_available_port() -> int:
    """获取一个可用的本地端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

def remove_captcha_image() -> None:
    """删除临时验证码图片及空目录"""
    file_path = 'images/captcha.png'
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError:
            pass
        try:
            os.rmdir('images')
        except OSError:
            pass

def cleanup_user_data(user_data_dir: str) -> None:
    """清理浏览器用户数据目录"""
    if os.path.exists(user_data_dir):
        try:
            shutil.rmtree(user_data_dir)
            print(f"✅ 已清除浏览器数据目录: {user_data_dir}")
        except OSError as e:
            print(f"⚠️ 清除浏览器数据目录失败（可忽略）: {e}")

def create_browser_page(chrome_path: str, headless: bool = False) -> ChromiumPage:
    """
    创建并返回 ChromiumPage 实例，根据 headless 配置启动选项
    """
    is_ci = os.environ.get('GITHUB_ACTIONS') == 'true'
    user_data_dir = os.path.join(os.getcwd(), 'chrome_user_data_ci' if (headless or is_ci) else 'chrome_user_data')

    co = ChromiumOptions()
    co.set_paths(browser_path=chrome_path)  # type: ignore

    if headless or is_ci:
        co.set_argument('--headless')
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-dev-shm-usage')
        co.set_argument('--disable-gpu')
        co.set_argument('--disable-software-rasterizer')
        co.set_argument('--disable-setuid-sandbox')
        co.set_argument('--disable-features=HttpsUpgrades')
        co.set_argument('--window-size=1920,1080')
        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        debug_port = get_available_port()
        co.set_argument(f'--remote-debugging-port={debug_port}')
        co.set_user_data_path(user_data_dir)
    else:
        co.auto_port(True)
        co.set_argument('--window-size=1920,1080')
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-gpu')
        co.set_argument('--disable-dev-shm-usage')
        co.set_user_data_path(user_data_dir)

    co.set_argument('--disable-cache')
    co.set_argument('--disable-application-cache')

    return ChromiumPage(co)

# ==================== 登录模块 ====================
def login_and_get_page(username: str, password: str,
                       headless: bool = False, max_retries: int = 5) -> Tuple[ChromiumPage, str]:
    """
    自动登录西南大学统一认证，从 localStorage 获取 access_token
    返回 (page, token)
    """
    chrome_path = get_chrome_path()
    print(f"✅ 使用 Chrome: {chrome_path}")

    is_ci = os.environ.get('GITHUB_ACTIONS') == 'true'
    user_data_dir = os.path.join(os.getcwd(), 'chrome_user_data_ci' if (headless or is_ci) else 'chrome_user_data')

    for attempt in range(1, max_retries + 1):
        print(f"\n--- 第 {attempt} 次尝试登录 ---")
        page = None
        try:
            page = create_browser_page(chrome_path, headless)
            print("✅ 浏览器启动成功")
        except Exception as e1:  # noinspection PyBroadException
            print(f"❌ 浏览器启动失败: {e1}")
            if headless or is_ci:
                try:
                    page = create_browser_page(chrome_path, False)
                    print("✅ 已切换到非无头模式启动（auto_port）")
                except Exception as e2:  # noinspection PyBroadException
                    print(f"❌ 非无头模式也启动失败: {e2}")
                    raise
            else:
                raise

        try:
            # 登录交互
            login_url = ('https://of.swu.edu.cn/cas/oauth/login/SWU_CAS2_FEDERAL'
                         '?service=https%3A%2F%2Fof.swu.edu.cn%2Fgateway%2Ffighter-middle%2Fapi%2Fintegrate%2Fuaap%2Fcas%2Fresolve-cas-return%3Fnext%3Dhttps%253A%252F%252Fof.swu.edu.cn%252F%2523%252FcasLogin%253Ffrom%253D%25252FappCenter')
            page.get(login_url)
            print(f"当前页面标题: {page.title}")
            print(f"当前URL: {page.url}")

            unified_btn = page.ele('@src=img/unified_button.png', timeout=5.0)
            if unified_btn:
                unified_btn.click()
                print("已点击统一认证按钮，等待跳转...")
                time.sleep(3)
                print(f"跳转后标题: {page.title}")
                print(f"跳转后URL: {page.url}")

            if 'Login' not in page.url:
                print("未进入登录页，尝试直接访问基础登录页...")
                page.get('https://idm.swu.edu.cn/am/UI/Login')
                time.sleep(2)
                print(f"基础登录页URL: {page.url}")

            print("等待登录表单加载...")
            time.sleep(1)

            iframes = page.eles('tag:iframe', timeout=3.0)
            if iframes:
                print(f"发现 {len(iframes)} 个 iframe，尝试切换到第一个")
                page.to_frame(iframes[0])  # type: ignore

            username_input = (page.ele('@name=username', timeout=3.0) or
                              page.ele('@name=j_username', timeout=3.0))
            if not username_input:
                inputs = page.eles('tag:input@type=text', timeout=3.0)
                if inputs:
                    username_input = inputs[0]
            if not username_input:
                raise RuntimeError("❌ 未找到用户名输入框")
            username_input.clear().input(username)
            print("✅ 已输入用户名")

            password_input = (page.ele('@name=password', timeout=3.0) or
                              page.ele('@name=j_password', timeout=3.0))
            if not password_input:
                inputs = page.eles('tag:input@type=password', timeout=3.0)
                if inputs:
                    password_input = inputs[0]
            if not password_input:
                raise RuntimeError("❌ 未找到密码输入框")
            password_input.clear().input(password)
            print("✅ 已输入密码")

            print("正在获取验证码...")
            time.sleep(0.5)
            img = page.ele('@id=kaptchaImage', timeout=5.0) or page.ele('@src=/am/validate.code', timeout=5.0)
            if not img:
                all_imgs = page.eles('tag:img', timeout=3.0)
                for i in all_imgs:
                    src = i.attr('src') or ''
                    if 'captcha' in src.lower() or 'code' in src.lower():
                        img = i
                        break
            if not img:
                raise RuntimeError("❌ 未找到验证码图片")

            os.makedirs('images', exist_ok=True)
            img.save(path='images', name='captcha.png')
            print("✅ 验证码图片已保存")

            with open('images/captcha.png', 'rb') as f:
                image_bytes = f.read()
            ocr = ddddocr.DdddOcr(show_ad=False)
            result = ocr.classification(image_bytes)
            print(f"识别到的验证码: {result}")

            captcha_input = (page.ele('@name=captcha', timeout=3.0) or
                             page.ele('@name=verificationCode', timeout=3.0))
            if not captcha_input:
                inputs = page.eles('tag:input@type=text', timeout=3.0)
                if inputs:
                    captcha_input = inputs[-1] if len(inputs) > 1 else inputs[0]
            if not captcha_input:
                captcha_input = page.ele('xpath://input[@type="text"][position()>2]', timeout=3.0)
            if not captcha_input:
                raise RuntimeError("❌ 未找到验证码输入框")

            captcha_input.clear()
            page.actions.click(captcha_input).wait(0.1)
            for ch in result:
                page.actions.type(ch).wait(0.05)
            if username_input:
                username_input.click()
            page.actions.wait(0.2)

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

            login_btn = (page.ele('@style=vertical-align: top;', timeout=3.0) or
                         page.ele('.btn.btn-default.blue', timeout=3.0) or
                         page.ele('tag:input@type=submit', timeout=3.0) or
                         page.ele('text=登录', timeout=3.0))
            if not login_btn:
                raise RuntimeError("❌ 未找到登录按钮")

            page.actions.move_to(login_btn).click().wait(0.5)
            print("✅ 已点击登录按钮")
            time.sleep(1)
            error_msgs = page.eles('.error, #err, .msg-error, .alert-danger', timeout=1.0)
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
                                return page, token
                            else:
                                print("⚠️ localStorage 中的 token 无效，继续等待...")
                                token = None
                        except Exception as e:  # noinspection PyBroadException
                            print(f"⚠️ 验证 token 时发生异常: {e}")
                            token = None
                else:
                    if entered_target:
                        entered_target = False

                elapsed = time.time() - start_time
                if int(elapsed) % 5 == 0:
                    print(f"⏳ 已等待 {elapsed:.0f}s，当前 URL: {current_url[:80]}...")

                time.sleep(0.2)

            raise RuntimeError("获取 token 超时（20s），未从 localStorage 获取到有效 access_token")

        except Exception as e:  # noinspection PyBroadException
            print(f"第 {attempt} 次尝试失败: {e}")
            remove_captcha_image()
            if page:
                try:
                    page.quit()
                except Exception:  # noinspection PyBroadException
                    pass
            cleanup_user_data(user_data_dir)
            if attempt == max_retries:
                raise
            else:
                print("等待 2 秒后重试...")
                time.sleep(2)

    raise RuntimeError(f"登录失败，已重试 {max_retries} 次。")

# ==================== 打卡模块 ====================
def get_transition_today(token: str) -> Optional[dict]:
    """获取今日任务（使用 requests 查询）"""
    url = "https://of.swu.edu.cn/gateway/fighter-baida/api/cqtj/getTransitionByToday"
    headers = {"fighter-auth-token": token}
    data = {"pageNum": 1, "pageSize": 1}
    try:
        resp = requests.post(url, headers=headers, data=data, timeout=10)
        resp.raise_for_status()
        resp_data = resp.json()
        records = resp_data.get("data", {}).get("records", [])
        return records[0] if records else None
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        raise RuntimeError(f"查询任务失败: {e}") from e

def get_student_id(token: str) -> str:
    """获取学号（使用 requests）"""
    url = "https://of.swu.edu.cn/gateway/fighter-middle/api/auth/user?appType=fighter-portal"
    headers = {"fighter-auth-token": token}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()["data"]["subject"]["username"]
    except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f"获取学号失败: {e}") from e

def checkin_with_page(page: ChromiumPage, token: str) -> Tuple[bool, str, int]:
    """使用浏览器页面提交打卡"""
    try:
        task = get_transition_today(token)
        if not task:
            return True, "今日无打卡任务", 10
        if task.get("qdzt") == "已签到":
            return True, "今日已签到，无需重复", 0

        student_id = get_student_id(token)
        print(f"当前用户学号: {student_id}")

        formid = task["formId"]
        record_id = task["id"]
        url = "https://of.swu.edu.cn/gateway/fighter-baida/api/form-instance/save"
        headers = {"fighter-auth-token": token, "Content-Type": "application/json;charset=UTF-8"}
        payload = {
            "id": record_id,
            "formId": formid,
            "tsrq": time.strftime("%Y-%m-%d"),
            "xh": student_id,
            "qdsj": CHECKIN_TIME_RANGE,
        }

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
    except Exception as e:  # noinspection PyBroadException
        return False, f"打卡过程中异常: {e}", 20

def fallback_checkin(tok: str) -> Tuple[bool, str, int]:
    """纯 requests 方式打卡（用于手动 token）"""
    try:
        task = get_transition_today(tok)
        if not task:
            return True, "今日无打卡任务", 10
        if task.get("qdzt") == "已签到":
            return True, "今日已签到，无需重复", 0

        stu_id = get_student_id(tok)
        formid = task["formId"]
        record_id = task["id"]
        url = "https://of.swu.edu.cn/gateway/fighter-baida/api/form-instance/save"
        headers = {"fighter-auth-token": tok, "Content-Type": "application/json;charset=UTF-8"}
        payload = {
            "id": record_id,
            "formId": formid,
            "tsrq": time.strftime("%Y-%m-%d"),
            "xh": stu_id,
            "qdsj": CHECKIN_TIME_RANGE,
        }
        resp = requests.post(url, headers=headers, params={"formId": formid, "isSubmitProcess": False},
                             data=json.dumps(payload), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 200 and data.get("data"):
            return True, "打卡成功！", 0
        else:
            return False, f"打卡失败: {data.get('msg', '未知错误')}", 20
    except Exception as e:  # noinspection PyBroadException
        return False, f"异常: {e}", 20

# ==================== 主程序 ====================
def main():
    parser = argparse.ArgumentParser(description='西南大学自动打卡（全程浏览器）')
    parser.add_argument('--no-headless', action='store_true', help='禁用无头模式（显示浏览器）')
    args = parser.parse_args()
    headless_mode = not args.no_headless

    username = os.environ.get('SWU_USERNAME')
    password = os.environ.get('SWU_PASSWORD')
    if not username or not password:
        print("❌ 请设置环境变量 SWU_USERNAME 和 SWU_PASSWORD")
        sys.exit(1)

    token = os.environ.get('SWU_TOKEN', '').strip() or MANUAL_TOKEN.strip()
    page = None

    if not token:
        print("未指定手动 token，将自动登录获取...")
        try:
            page, token = login_and_get_page(username, password, headless=headless_mode)
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

    print("\n--- 开始打卡 ---")
    # noinspection PyUnusedLocal
    if page is not None:   # 显式使用 page
        success, reason, exit_code = checkin_with_page(page, token)
    else:
        # 显式引用 page 以消除未使用警告（实际不会执行）
        _ = page
        success, reason, exit_code = fallback_checkin(token)

    # 清理浏览器资源
    if page is not None:
        try:
            page.quit()
            print("✅ 浏览器已关闭")
        except Exception:  # noinspection PyBroadException
            pass
        is_ci = os.environ.get('GITHUB_ACTIONS') == 'true'
        user_data_dir = os.path.join(os.getcwd(), 'chrome_user_data_ci' if (headless_mode or is_ci) else 'chrome_user_data')
        cleanup_user_data(user_data_dir)

    if success:
        print(f"✅ 打卡流程完成：{reason}")
        sys.exit(0)
    else:
        print(f"❌ 打卡失败：{reason}")
        sys.exit(exit_code)

if __name__ == "__main__":
    main()
