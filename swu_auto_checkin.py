#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import json
import argparse
import subprocess
import urllib.parse
import socket
import ddddocr
import requests
from DrissionPage import ChromiumPage, ChromiumOptions

# ==================== 配置区 ====================
MANUAL_TOKEN = ""                     # 留空则自动登录
CHECKIN_TIME_RANGE = ["21:00", "23:30"]

# ==================== 工具函数 ====================
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

# ==================== 登录模块 ====================
def exchange_token_with_code(code: str) -> str:
    """
    使用授权码 code 换取真正的 fighter-auth-token
    """
    url = "https://of.swu.edu.cn/gateway/fighter-middle/api/integrate/uaap/cas/exchange-token"
    params = {
        "token": code,
        "remember": "true"
    }
    resp = requests.get(url, params=params)
    if resp.status_code != 200:
        raise Exception(f"换取 token 失败，HTTP状态码: {resp.status_code}")
    data = resp.json()
    if "data" in data and data["data"]:
        return data["data"]
    else:
        raise Exception(f"换取 token 失败: {data.get('msg', '未知错误')}")

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

            # ---------- 核心：从回调 URL 提取 code 并交换 token ----------
            print("等待登录成功后跳转...")
            for i in range(60):  # 最多等待30秒
                time.sleep(0.5)
                current_url = dp.url
                # 优先：URL 包含 code 参数（通常在 of.swu.edu.cn 域名下）
                if 'code=' in current_url and 'of.swu.edu.cn' in current_url:
                    parsed = urllib.parse.urlparse(current_url)
                    params = urllib.parse.parse_qs(parsed.query)
                    if 'code' in params:
                        code = params['code'][0]
                        print(f"获取到授权码 code: {code[:10]}...")
                        try:
                            real_token = exchange_token_with_code(code)
                            print("✅ 成功换取访问令牌")
                            # 清理临时文件
                            if os.path.exists(file_path):
                                os.remove(file_path)
                                try:
                                    os.rmdir('images')
                                except:
                                    pass
                            return real_token
                        except Exception as e:
                            raise Exception(f"换取 token 失败: {e}")
                # 备选：如果已经跳转到 of 主页且没有 code，尝试从 localStorage 取（用于兼容手动调试）
                if 'of.swu.edu.cn' in current_url and 'code' not in current_url:
                    token = dp.run_js('''
                        return localStorage.getItem('access_token') || 
                               localStorage.getItem('token') ||
                               sessionStorage.getItem('access_token') ||
                               sessionStorage.getItem('token');
                    ''')
                    if token:
                        print("✅ 从 localStorage/sessionStorage 获取 token 成功，尝试验证有效性...")
                        try:
                            test_url = "https://of.swu.edu.cn/gateway/fighter-middle/api/auth/user?appType=fighter-portal"
                            test_headers = {"fighter-auth-token": token}
                            test_resp = requests.get(test_url, headers=test_headers)
                            if test_resp.status_code == 200:
                                print("✅ localStorage 中的 token 有效")
                                if os.path.exists(file_path):
                                    os.remove(file_path)
                                    try:
                                        os.rmdir('images')
                                    except:
                                        pass
                                return token
                            else:
                                print("⚠️ localStorage 中的 token 无效，继续等待...")
                        except:
                            pass
                if i % 10 == 0:
                    print(f"当前 URL ({i*0.5}s): {current_url[:100]}...")

            raise Exception("获取 token 超时，未获取到有效的授权码或访问令牌")

        except Exception as e:
            print(f"第 {attempt} 次尝试失败: {e}")
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
        finally:
            try:
                dp.quit()
            except:
                pass

    raise Exception(f"登录失败，已重试 {max_retries} 次。")

# ==================== 打卡模块 ====================
def get_transition_today(token: str):
    """查询今日打卡任务"""
    url = "https://of.swu.edu.cn/gateway/fighter-baida/api/cqtj/getTransitionByToday"
    headers = {"fighter-auth-token": token}
    data = {"pageNum": 1, "pageSize": 1}
    resp = requests.post(url, headers=headers, data=data)
    if resp.status_code != 200:
        raise Exception(f"查询任务失败，HTTP状态码: {resp.status_code}")
    resp_data = resp.json()
    records = resp_data.get("data", {}).get("records", [])
    return records[0] if records else None

def get_student_id(token: str):
    """获取当前登录用户的学号"""
    url = "https://of.swu.edu.cn/gateway/fighter-middle/api/auth/user?appType=fighter-portal"
    headers = {"fighter-auth-token": token}
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        raise Exception(f"获取学号失败，HTTP状态码: {resp.status_code}")
    return resp.json()["data"]["subject"]["username"]

def checkin(token: str):
    """
    执行打卡，返回 (success, reason, exit_code)
    exit_code: 0=成功/已签到, 10=无任务, 20=失败
    """
    try:
        # 1. 获取今日任务
        task = get_transition_today(token)
        if not task:
            msg = "今日无打卡任务"
            print(f"ℹ️ {msg}")
            return True, msg, 10   # 无任务视为正常

        # 2. 检查是否已签到
        if task.get("qdzt") == "已签到":
            msg = "今日已签到，无需重复"
            print(f"✅ {msg}")
            return True, msg, 0    # 已签到视为成功

        # 3. 未签到，执行打卡
        student_id = get_student_id(token)
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

        resp = requests.post(url, headers=headers, params=params, data=json.dumps(payload))
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 200 and data.get("data"):
            msg = "打卡成功！"
            print(f"✅ {msg}")
            return True, msg, 0
        else:
            msg = f"打卡失败: {data.get('msg', '未知错误')}"
            print(f"❌ {msg}")
            return False, msg, 20

    except requests.exceptions.RequestException as e:
        msg = f"网络请求异常: {e}"
        print(f"❌ {msg}")
        return False, msg, 20
    except Exception as e:
        msg = f"未知异常: {e}"
        print(f"❌ {msg}")
        return False, msg, 20

# ==================== 主程序 ====================
def main():
    parser = argparse.ArgumentParser(description='西南大学自动打卡（含自动登录）')
    parser.add_argument('--no-headless', action='store_true', help='禁用无头模式（显示浏览器）')
    args = parser.parse_args()
    headless_mode = not args.no_headless

    username = os.environ.get('SWU_USERNAME')
    password = os.environ.get('SWU_PASSWORD')
    if not username or not password:
        print("❌ 请设置环境变量 SWU_USERNAME 和 SWU_PASSWORD")
        sys.exit(1)

    token = MANUAL_TOKEN.strip()
    if not token:
        print("未指定手动 token，将自动登录获取...")
        try:
            token = get_swu_token(username, password, headless=headless_mode)
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

    # 执行打卡
    print("\n--- 开始打卡 ---")
    success, reason, exit_code = checkin(token)
    if success:
        # 所有成功情况（包括已签到、无任务）都返回0，但日志已区分
        print(f"✅ 打卡流程完成：{reason}")
        sys.exit(0)
    else:
        print(f"❌ 打卡失败：{reason}")
        sys.exit(1)

if __name__ == "__main__":
    main()
