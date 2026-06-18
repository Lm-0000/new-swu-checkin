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

def get_chrome_path():
    chrome_path = os.environ.get('CHROME_PATH')
    if chrome_path and os.path.isfile(chrome_path):
        return chrome_path
    for path in ['/usr/bin/google-chrome', '/usr/bin/chromium-browser', '/usr/bin/chromium',
                 '/opt/google/chrome/chrome']:
        if os.path.isfile(path):
            return path
    for path in [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]:
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

# ---------- 登录模块（完整保留，无修改） ----------
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
            unified_btn = dp.ele('@src=img/unified_button.png', timeout=5)
            if unified_btn:
                unified_btn.click()
                time.sleep(3)
            if 'Login' not in dp.url:
                dp.get('https://idm.swu.edu.cn/am/UI/Login')
                time.sleep(2)
            time.sleep(1)
            iframes = dp.eles('tag:iframe', timeout=3)
            if iframes:
                dp.to_frame(iframes[0])
                time.sleep(1)

            username_input = dp.ele('@name=username', timeout=3) or dp.ele('@name=j_username', timeout=3)
            if not username_input:
                inputs = dp.eles('tag:input@type=text', timeout=3)
                username_input = inputs[0] if inputs else None
            if not username_input:
                raise Exception("❌ 未找到用户名输入框")
            username_input.clear().input(username)

            password_input = dp.ele('@name=password', timeout=3) or dp.ele('@name=j_password', timeout=3)
            if not password_input:
                inputs = dp.eles('tag:input@type=password', timeout=3)
                password_input = inputs[0] if inputs else None
            if not password_input:
                raise Exception("❌ 未找到密码输入框")
            password_input.clear().input(password)

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
            if os.path.exists(file_path): os.remove(file_path)
            img.save(path='images', name='captcha.png')
            with open(file_path, 'rb') as f:
                image_bytes = f.read()
            ocr = ddddocr.DdddOcr(show_ad=False)
            result = ocr.classification(image_bytes)
            print(f"验证码: {result}")

            captcha_input = dp.ele('@name=captcha', timeout=3) or dp.ele('@name=verificationCode', timeout=3)
            if not captcha_input:
                inputs = dp.eles('tag:input@type=text', timeout=3)
                captcha_input = inputs[-1] if inputs else None
            if not captcha_input:
                captcha_input = dp.ele('xpath://input[@type="text"][position()>2]', timeout=3)
            if not captcha_input:
                raise Exception("❌ 未找到验证码输入框")
            captcha_input.clear()
            dp.actions.click(captcha_input).wait(0.1)
            for ch in result:
                dp.actions.type(ch).wait(0.05)
            dp.run_js('''
                var el = arguments[0];
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: true }));
                el.dispatchEvent(new Event('keyup', { bubbles: true }));
                el.dispatchEvent(new Event('keydown', { bubbles: true }));
            ''', captcha_input)
            time.sleep(0.3)

            login_btn = dp.ele('@style=vertical-align: top;', timeout=3) or dp.ele('.btn.btn-default.blue', timeout=3) or dp.ele('tag:input@type=submit', timeout=3) or dp.ele('text=登录', timeout=3)
            if not login_btn:
                raise Exception("❌ 未找到登录按钮")
            dp.actions.move_to(login_btn).click().wait(0.5)

            time.sleep(3)
            if 'Login' in dp.url or 'idm.swu.edu.cn' in dp.url:
                dp.run_js('''
                    var btn = document.querySelector('[style*="vertical-align: top"]');
                    if (!btn) btn = document.querySelector('.btn.btn-default.blue');
                    if (!btn) btn = document.querySelector('input[type="submit"]');
                    if (btn) btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                ''')
                time.sleep(3)
                if 'Login' in dp.url or 'idm.swu.edu.cn' in dp.url:
                    raise Exception("登录失败，验证码错误或账号密码不正确")

            for i in range(60):
                time.sleep(0.5)
                token = dp.run_js('return localStorage.getItem("access_token") || localStorage.getItem("token") || sessionStorage.getItem("access_token") || sessionStorage.getItem("token")')
                if token:
                    print("✅ token 获取成功")
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        try: os.rmdir('images')
                        except: pass
                    return token, dp
                current_url = dp.url
                if 'code=' in current_url:
                    parsed = urllib.parse.urlparse(current_url)
                    params = urllib.parse.parse_qs(parsed.query)
                    if 'code' in params:
                        token = params['code'][0]
                        print(f"✅ code token: {token}")
                        return token, dp
                for cookie in dp.cookies():
                    if 'token' in cookie['name'].lower() or 'access' in cookie['name'].lower():
                        token = cookie['value']
                        print(f"✅ cookie token: {cookie['name']}")
                        return token, dp
                if i % 10 == 0:
                    print(f"等待登录中... ({i*0.5}s)")
            raise Exception("未获取到 token")
        except Exception as e:
            print(f"第 {attempt} 次尝试失败: {e}")
            try: dp.quit()
            except: pass
            if os.path.exists('images/captcha.png'):
                os.remove('images/captcha.png')
                try: os.rmdir('images')
                except: pass
            if attempt == max_retries:
                raise
            else:
                time.sleep(2)
    raise Exception(f"登录失败，已重试 {max_retries} 次。")

# ---------- 打卡模块（自动选择模式） ----------
def is_github_actions():
    return os.environ.get('GITHUB_ACTIONS') == 'true'

# 原始 requests 打卡（本地使用）
def checkin_requests(token):
    def get_transition_today(t):
        url = "https://of.swu.edu.cn/gateway/fighter-baida/api/cqtj/getTransitionByToday"
        headers = {"fighter-auth-token": t}
        data = {"pageNum": 1, "pageSize": 1}
        resp = requests.post(url, headers=headers, data=data, timeout=10).json()
        records = resp.get("data", {}).get("records", [])
        return records[0] if records else None

    def get_student_id(t):
        url = "https://of.swu.edu.cn/gateway/fighter-middle/api/auth/user?appType=fighter-portal"
        headers = {"fighter-auth-token": t}
        resp = requests.get(url, headers=headers, timeout=10).json()
        return resp["data"]["subject"]["username"]

    task = get_transition_today(token)
    if not task:
        print("❌ 今日无打卡任务")
        return False
    if task.get("qdzt") == "已签到":
        print("✅ 今日已打卡")
        return True

    student_id = get_student_id(token)
    print(f"学号: {student_id}")

    formid = task["formId"]
    record_id = task["id"]
    url = "https://of.swu.edu.cn/gateway/fighter-baida/api/form-instance/save"
    params = {"formId": formid, "isSubmitProcess": False}
    headers = {"fighter-auth-token": token, "Content-Type": "application/json;charset=UTF-8"}
    payload = {"id": record_id, "formId": formid, "tsrq": time.strftime("%Y-%m-%d"), "xh": student_id, "qdsj": CHECKIN_TIME_RANGE}
    resp = requests.post(url, headers=headers, params=params, data=json.dumps(payload), timeout=10).json()
    if resp.get("code") == 200 and resp.get("data"):
        print("✅ 打卡成功！")
        return True
    else:
        print(f"❌ 打卡失败: {resp.get('msg', '未知错误')}")
        return False

# 浏览器内 fetch 打卡（GitHub Actions 使用）
def checkin_browser(token, dp):
    def api_request(url, method='GET', headers=None, data=None, json_data=None, params=None):
        dp.run_js('delete window.__api_result')
        headers_js = json.dumps(headers) if headers else '{}'
        if params:
            url = url + '?' + urllib.parse.urlencode(params)
        body = json_data if json_data else data
        body_js = json.dumps(body) if body else 'null'

        js = f'''
        (async () => {{
            const options = {{ method: '{method}', headers: {headers_js} }};
            if (options.method !== 'GET') options.body = JSON.stringify({body_js});
            try {{
                const resp = await fetch('{url}', options);
                const data = await resp.json();
                window.__api_result = JSON.stringify(data);
            }} catch (e) {{
                window.__api_result = JSON.stringify({{error: e.message}});
            }}
        }})()
        '''
        dp.run_js(js)
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

    dp.get('https://of.swu.edu.cn')
    time.sleep(3)

    task_resp = api_request("https://of.swu.edu.cn/gateway/fighter-baida/api/cqtj/getTransitionByToday",
                            method='POST', headers={"fighter-auth-token": token},
                            data={"pageNum": 1, "pageSize": 1})
    records = task_resp.get("data", {}).get("records", [])
    task = records[0] if records else None
    if not task:
        print("❌ 今日无打卡任务")
        return False
    if task.get("qdzt") == "已签到":
        print("✅ 今日已打卡")
        return True

    user_resp = api_request("https://of.swu.edu.cn/gateway/fighter-middle/api/auth/user?appType=fighter-portal",
                            method='GET', headers={"fighter-auth-token": token})
    student_id = user_resp["data"]["subject"]["username"]
    print(f"学号: {student_id}")

    formid = task["formId"]
    record_id = task["id"]
    save_url = "https://of.swu.edu.cn/gateway/fighter-baida/api/form-instance/save"
    params = {"formId": formid, "isSubmitProcess": False}
    headers = {"fighter-auth-token": token, "Content-Type": "application/json;charset=UTF-8"}
    payload = {"id": record_id, "formId": formid, "tsrq": time.strftime("%Y-%m-%d"), "xh": student_id, "qdsj": CHECKIN_TIME_RANGE}
    save_resp = api_request(save_url, method='POST', headers=headers, json_data=payload, params=params)
    if save_resp.get("code") == 200 and save_resp.get("data"):
        print("✅ 打卡成功！")
        return True
    else:
        print(f"❌ 打卡失败: {save_resp.get('msg', '未知错误')}")
        return False

# 统一入口
def checkin(token, dp=None):
    if is_github_actions():
        print("检测到 GitHub Actions 环境，使用浏览器内部请求...")
        if not dp:
            raise Exception("浏览器对象未传入")
        return checkin_browser(token, dp)
    else:
        print("本地环境，使用 Python requests...")
        return checkin_requests(token)

# ---------- 主程序 ----------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-headless', action='store_true')
    args = parser.parse_args()
    headless_mode = not args.no_headless

    username = os.environ.get('SWU_USERNAME')
    password = os.environ.get('SWU_PASSWORD')
    if not username or not password:
        raise Exception("❌ 请设置环境变量 SWU_USERNAME 和 SWU_PASSWORD")

    token = MANUAL_TOKEN.strip()
    dp = None
    if not token:
        print("自动登录获取 token...")
        try:
            token, dp = get_swu_token(username, password, headless=headless_mode)
            print(f"token: {token[:10]}...")
        except Exception as e:
            print(f"❌ 自动登录失败: {e}")
            return
    else:
        print(f"使用手动 token: {token[:10]}...")
        if is_github_actions():
            print("Actions 中暂不支持手动 token，请留空自动登录")
            return
        success = checkin(token)
        if success:
            print("打卡流程完成。")
        else:
            print("打卡失败。")
        return

    print("\n--- 开始打卡 ---")
    try:
        success = checkin(token, dp)
        if success:
            print("打卡流程完成。")
        else:
            print("打卡失败。")
    finally:
        if dp:
            dp.quit()
            if os.path.exists('images/captcha.png'):
                os.remove('images/captcha.png')
                try: os.rmdir('images')
                except: pass

if __name__ == "__main__":
    main()
