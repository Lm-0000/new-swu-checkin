#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import json
import argparse
import subprocess
import urllib.parse
import socket
import ddddocr
import requests
from DrissionPage import ChromiumPage, ChromiumOptions

MANUAL_TOKEN = ""
CHECKIN_TIME_RANGE = ["21:00", "23:30"]

# ---------- 工具函数 ----------
def get_chrome_path():
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
    except:
        pass
    raise Exception("❌ 未找到 Chrome 浏览器")

def get_available_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

# ---------- 登录模块 ----------
def get_swu_token(username: str, password: str, headless: bool = False, max_retries: int = 3):
    chrome_path = get_chrome_path()
    print(f"✅ 使用 Chrome: {chrome_path}")

    for attempt in range(1, max_retries + 1):
        print(f"\n--- 第 {attempt} 次尝试登录 ---")
        co = ChromiumOptions()
        co.set_paths(browser_path=chrome_path)

        is_ci = os.environ.get('GITHUB_ACTIONS') == 'true'
        if headless or is_ci:
            co.set_argument('--headless=new')
            co.set_argument('--no-sandbox')
            co.set_argument('--disable-dev-shm-usage')
            co.set_argument('--disable-gpu')
            co.set_argument('--window-size=1920,1080')
            co.set_argument('--disable-blink-features=AutomationControlled')
            co.set_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            debug_port = get_available_port()
            co.set_argument(f'--remote-debugging-port={debug_port}')
            co.set_user_data_path(os.path.join(os.getcwd(), 'chrome_user_data_ci'))
        else:
            co.auto_port(True)
            co.set_argument('--window-size=1920,1080')
            co.set_argument('--no-sandbox')
            co.set_argument('--disable-gpu')
            co.set_argument('--disable-dev-shm-usage')
            co.set_user_data_path('./chrome_user_data')

        co.set_argument('--disable-cache')
        co.set_argument('--disable-application-cache')

        try:
            dp = ChromiumPage(co)
            print("✅ 浏览器启动成功")
        except Exception as e:
            print(f"❌ 浏览器启动失败: {e}")
            if headless or is_ci:
                co = ChromiumOptions()
                co.set_paths(browser_path=chrome_path)
                co.auto_port(True)
                co.set_argument('--window-size=1920,1080')
                co.set_argument('--no-sandbox')
                co.set_argument('--disable-gpu')
                co.set_argument('--disable-dev-shm-usage')
                dp = ChromiumPage(co)
                print("✅ 已切换到非无头模式启动")
            else:
                raise

        try:
            login_url = 'https://of.swu.edu.cn/cas/oauth/login/SWU_CAS2_FEDERAL?service=https%3A%2F%2Fof.swu.edu.cn%2Fgateway%2Ffighter-middle%2Fapi%2Fintegrate%2Fuaap%2Fcas%2Fresolve-cas-return%3Fnext%3Dhttps%253A%252F%252Fof.swu.edu.cn%252F%2523%252FcasLogin%253Ffrom%253D%25252FappCenter'
            dp.get(login_url)
            print(f"当前页面标题: {dp.title}")
            print(f"当前URL: {dp.url}")

            unified_btn = dp.ele('@src=img/unified_button.png', timeout=5)
            if unified_btn:
                unified_btn.click()
                print("已点击统一认证按钮，等待跳转...")
                time.sleep(3)
                print(f"跳转后标题: {dp.title}")
                print(f"跳转后URL: {dp.url}")

            if 'Login' not in dp.url:
                print("未进入登录页，尝试直接访问基础登录页...")
                dp.get('https://idm.swu.edu.cn/am/UI/Login')
                time.sleep(2)
                print(f"基础登录页URL: {dp.url}")

            print("等待登录表单加载...")
            time.sleep(1)

            iframes = dp.eles('tag:iframe', timeout=3)
            if iframes:
                print(f"发现 {len(iframes)} 个 iframe，尝试切换到第一个")
                dp.to_frame(iframes[0])
                time.sleep(1)

            username_input = dp.ele('@name=username', timeout=3) or dp.ele('@name=j_username', timeout=3)
            if not username_input:
                inputs = dp.eles('tag:input@type=text', timeout=3)
                if inputs:
                    username_input = inputs[0]
            if not username_input:
                raise Exception("❌ 未找到用户名输入框")
            username_input.clear().input(username)
            print("✅ 已输入用户名")

            password_input = dp.ele('@name=password', timeout=3) or dp.ele('@name=j_password', timeout=3)
            if not password_input:
                inputs = dp.eles('tag:input@type=password', timeout=3)
                if inputs:
                    password_input = inputs[0]
            if not password_input:
                raise Exception("❌ 未找到密码输入框")
            password_input.clear().input(password)
            print("✅ 已输入密码")

            print("正在获取验证码...")
            time.sleep(0.5)
            img = dp.ele('@id=kaptchaImage', timeout=5) or dp.ele('@src=/am/validate.code', timeout=5)
            if not img:
                all_imgs = dp.eles('tag:img', timeout=3)
                for i in all_imgs:
                    src = i.attr('src') or ''
                    if 'captcha' in src.lower() or 'code' in src.lower():
                        img = i
                        break
            if not img:
                raise Exception("❌ 未找到验证码图片")

            os.makedirs('images', exist_ok=True)
            file_path = 'images/captcha.png'
            if os.path.exists(file_path):
                os.remove(file_path)
            img.save(path='images', name='captcha.png')
            print("✅ 验证码图片已保存")

            with open(file_path, 'rb') as f:
                image_bytes = f.read()
            ocr = ddddocr.DdddOcr(show_ad=False)
            result = ocr.classification(image_bytes)
            print(f"识别到的验证码: {result}")

            captcha_input = dp.ele('@name=captcha', timeout=3) or dp.ele('@name=verificationCode', timeout=3)
            if not captcha_input:
                inputs = dp.eles('tag:input@type=text', timeout=3)
                if inputs:
                    if len(inputs) > 1:
                        captcha_input = inputs[-1]
                    else:
                        captcha_input = inputs[0]
            if not captcha_input:
                captcha_input = dp.ele('xpath://input[@type="text"][position()>2]', timeout=3)
            if not captcha_input:
                raise Exception("❌ 未找到验证码输入框")

            captcha_input.clear()
            dp.actions.click(captcha_input).wait(0.1)
            for ch in result:
                dp.actions.type(ch).wait(0.05)
            if username_input:
                username_input.click()
            dp.actions.wait(0.2)

            dp.run_js('''
                var el = arguments[0];
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: true }));
                el.dispatchEvent(new Event('keyup', { bubbles: true }));
                el.dispatchEvent(new Event('keydown', { bubbles: true }));
            ''', captcha_input)
            time.sleep(0.3)
            print("✅ 已输入验证码")

            login_btn = dp.ele('@style=vertical-align: top;', timeout=3)
            if not login_btn:
                login_btn = dp.ele('.btn.btn-default.blue', timeout=3)
            if not login_btn:
                login_btn = dp.ele('tag:input@type=submit', timeout=3)
            if not login_btn:
                login_btn = dp.ele('text=登录', timeout=3)
            if not login_btn:
                raise Exception("❌ 未找到登录按钮")

            dp.actions.move_to(login_btn).click().wait(0.5)
            print("✅ 已点击登录按钮")

            time.sleep(3)
            error_msgs = dp.eles('.error, #err, .msg-error, .alert-danger', timeout=1)
            if error_msgs:
                for e in error_msgs:
                    print(f"⚠️ 错误信息: {e.text}")
                raise Exception(f"登录失败: {error_msgs[0].text}")

            if 'Login' in dp.url or 'idm.swu.edu.cn' in dp.url:
                print("⚠️ 页面未跳转，尝试使用 JavaScript 触发按钮...")
                dp.run_js('''
                    var btn = document.querySelector('[style*="vertical-align: top"]');
                    if (!btn) btn = document.querySelector('.btn.btn-default.blue');
                    if (!btn) btn = document.querySelector('input[type="submit"]');
                    if (btn) {
                        btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                    }
                ''')
                time.sleep(3)
                if 'Login' in dp.url or 'idm.swu.edu.cn' in dp.url:
                    raise Exception("登录失败，可能是验证码错误或账号密码不正确")

            # 获取 token
            for i in range(60):
                time.sleep(0.5)
                token = dp.run_js('''
                    return localStorage.getItem('access_token') || 
                           localStorage.getItem('token') ||
                           sessionStorage.getItem('access_token') ||
                           sessionStorage.getItem('token');
                ''')
                if token:
                    print("✅ 从 localStorage/sessionStorage 获取 token 成功")
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        try:
                            os.rmdir('images')
                        except:
                            pass
                    return token, dp
                current_url = dp.url
                if 'code=' in current_url:
                    parsed = urllib.parse.urlparse(current_url)
                    params = urllib.parse.parse_qs(parsed.query)
                    if 'code' in params:
                        token = params['code'][0]
                        print(f"✅ 从 URL 获取 code: {token}")
                        return token, dp
                for cookie in dp.cookies():
                    if 'token' in cookie['name'].lower() or 'access' in cookie['name'].lower():
                        token = cookie['value']
                        print(f"✅ 从 cookie 获取 token: {cookie['name']}")
                        return token, dp
                if i % 10 == 0:
                    print(f"当前 URL ({i*0.5}s): {current_url[:100]}...")

            raise Exception("未获取到 token")

        except Exception as e:
            print(f"第 {attempt} 次尝试失败: {e}")
            try:
                dp.quit()
            except:
                pass
            if os.path.exists('images/captcha.png'):
                os.remove('images/captcha.png')
                try:
                    os.rmdir('images')
                except:
                    pass
            if attempt == max_retries:
                raise
            else:
                print("等待 2 秒后重试...")
                time.sleep(2)

    raise Exception(f"登录失败，已重试 {max_retries} 次。")

# ---------- 打卡模块（自动选择 requests 或浏览器 fetch） ----------
def is_github_actions():
    return os.environ.get('GITHUB_ACTIONS') == 'true'

# 原始 requests 实现（本地可用）
def get_transition_today_requests(token):
    url = "https://of.swu.edu.cn/gateway/fighter-baida/api/cqtj/getTransitionByToday"
    headers = {"fighter-auth-token": token}
    data = {"pageNum": 1, "pageSize": 1}
    resp = requests.post(url, headers=headers, data=data).json()
    records = resp.get("data", {}).get("records", [])
    return records[0] if records else None

def get_student_id_requests(token):
    url = "https://of.swu.edu.cn/gateway/fighter-middle/api/auth/user?appType=fighter-portal"
    headers = {"fighter-auth-token": token}
    resp = requests.get(url, headers=headers).json()
    return resp["data"]["subject"]["username"]

def checkin_requests(token):
    task = get_transition_today_requests(token)
    if not task:
        print("❌ 今日无打卡任务")
        return False
    if task.get("qdzt") == "已签到":
        print("✅ 今日已打卡，无需重复")
        return True

    student_id = get_student_id_requests(token)
    print(f"当前用户学号: {student_id}")

    formid = task["formId"]
    record_id = task["id"]
    url = "https://of.swu.edu.cn/gateway/fighter-baida/api/form-instance/save"
    params = {"formId": formid, "isSubmitProcess": False}
    headers = {
        "fighter-auth-token": token,
        "Content-Type": "application/json;charset=UTF-8"
    }
    payload = {
        "id": record_id,
        "formId": formid,
        "tsrq": time.strftime("%Y-%m-%d"),
        "xh": student_id,
        "qdsj": CHECKIN_TIME_RANGE,
    }
    resp = requests.post(url, headers=headers, params=params, data=json.dumps(payload)).json()
    if resp.get("code") == 200 and resp.get("data"):
        print("✅ 打卡成功！")
        return True
    else:
        print(f"❌ 打卡失败: {resp.get('msg', '未知错误')}")
        return False

# 浏览器 fetch 实现（GitHub Actions 自动运行使用）
def api_request(dp, url, method='GET', headers=None, data=None, json_data=None, params=None):
    dp.run_js('delete window.__api_result')
    headers_js = json.dumps(headers) if headers else '{}'
    if params:
        url_with_params = url + '?' + urllib.parse.urlencode(params)
    else:
        url_with_params = url
    body = json_data if json_data else data
    body_js = json.dumps(body) if body else 'null'

    js_code = f'''
    (async () => {{
        const options = {{
            method: '{method}',
            headers: {headers_js},
        }};
        if (options.method !== 'GET') {{
            options.body = JSON.stringify({body_js});
        }}
        try {{
            const resp = await fetch('{url_with_params}', options);
            const data = await resp.json();
            window.__api_result = JSON.stringify(data);
        }} catch (e) {{
            window.__api_result = JSON.stringify({{error: e.message}});
        }}
    }})()
    '''
    dp.run_js(js_code)
    for _ in range(60):
        result = dp.run_js('return window.__api_result')
        if result:
            break
        time.sleep(0.5)
    else:
        raise Exception("等待 API 响应超时")
    data = json.loads(result)
    if isinstance(data, dict) and 'error' in data:
        raise Exception(data['error'])
    return data

def checkin_browser(token, dp):
    print("正在跳转到办事大厅首页...")
    dp.get('https://of.swu.edu.cn')
    time.sleep(3)
    print(f"当前页面 URL: {dp.url}")

    # 1. 获取今日任务
    task_data = api_request(dp, "https://of.swu.edu.cn/gateway/fighter-baida/api/cqtj/getTransitionByToday",
                            method='POST', headers={"fighter-auth-token": token},
                            data={"pageNum": 1, "pageSize": 1})
    records = task_data.get("data", {}).get("records", [])
    task = records[0] if records else None
    if not task:
        print("❌ 今日无打卡任务")
        return False
    if task.get("qdzt") == "已签到":
        print("✅ 今日已打卡，无需重复")
        return True

    # 2. 获取学号
    user_data = api_request(dp, "https://of.swu.edu.cn/gateway/fighter-middle/api/auth/user?appType=fighter-portal",
                            method='GET', headers={"fighter-auth-token": token})
    student_id = user_data["data"]["subject"]["username"]
    print(f"当前用户学号: {student_id}")

    # 3. 提交打卡
    formid = task["formId"]
    record_id = task["id"]
    url = "https://of.swu.edu.cn/gateway/fighter-baida/api/form-instance/save"
    params = {"formId": formid, "isSubmitProcess": False}
    headers = {
        "fighter-auth-token": token,
        "Content-Type": "application/json;charset=UTF-8"
    }
    payload = {
        "id": record_id,
        "formId": formid,
        "tsrq": time.strftime("%Y-%m-%d"),
        "xh": student_id,
        "qdsj": CHECKIN_TIME_RANGE,
    }
    save_data = api_request(dp, url, method='POST', headers=headers, json_data=payload, params=params)
    if save_data.get("code") == 200 and save_data.get("data"):
        print("✅ 打卡成功！")
        return True
    else:
        print(f"❌ 打卡失败: {save_data.get('msg', '未知错误')}")
        return False

# 统一的打卡入口，自动选择方式
def checkin(token, dp=None):
    if is_github_actions():
        print("检测到 GitHub Actions 环境，使用浏览器内部请求...")
        if not dp:
            raise Exception("浏览器对象未传入，无法在 Actions 中运行")
        return checkin_browser(token, dp)
    else:
        print("本地环境，使用 Python requests 请求...")
        return checkin_requests(token)

# ---------- 主程序 ----------
def main():
    parser = argparse.ArgumentParser(description='西南大学自动打卡（含自动登录）')
    parser.add_argument('--no-headless', action='store_true', help='禁用无头模式（显示浏览器）')
    args = parser.parse_args()
    headless_mode = not args.no_headless

    username = os.environ.get('SWU_USERNAME')
    password = os.environ.get('SWU_PASSWORD')
    if not username or not password:
        raise Exception("❌ 请设置环境变量 SWU_USERNAME 和 SWU_PASSWORD")

    token = MANUAL_TOKEN.strip()
    dp = None
    if not token:
        print("未指定手动 token，将自动登录获取...")
        try:
            token, dp = get_swu_token(username, password, headless=headless_mode)
            print(f"\n✅ 获取到的 token: {token[:10]}...")
        except Exception as e:
            print(f"❌ 自动登录失败: {e}")
            return
    else:
        print(f"使用手动指定的 token: {token[:10]}...")
        # 手动 token 模式：如果不在 Actions 中，可以用 requests 直接打卡（无需浏览器）
        if is_github_actions():
            print("Actions 中暂不支持手动 token，请留空自动登录")
            return
        # 本地手动 token，直接 requests 打卡
        success = checkin(token)  # 本地会调用 checkin_requests
        if success:
            print("打卡流程完成。")
        else:
            print("打卡失败，请检查网络或 token 状态。")
        return

    # 自动登录成功后，执行打卡
    print("\n--- 开始打卡 ---")
    try:
        success = checkin(token, dp)
        if success:
            print("打卡流程完成。")
        else:
            print("打卡失败，请检查网络或 token 状态。")
    finally:
        if dp:
            dp.quit()
            if os.path.exists('images/captcha.png'):
                os.remove('images/captcha.png')
                try:
                    os.rmdir('images')
                except:
                    pass

if __name__ == "__main__":
    main()
