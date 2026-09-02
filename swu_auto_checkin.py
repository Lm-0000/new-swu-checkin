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

# ==================== 登录模块（返回浏览器对象和token） ====================
def login_and_get_page(username: str, password: str, headless: bool = False, max_retries: int = 5):
    """
    自动登录西南大学统一认证，从 localStorage 获取 access_token
    返回 (page, token)，page 为已登录的浏览器页面，token 为有效凭证
    """
    chrome_path = get_chrome_path()
    print(f"✅ 使用 Chrome: {chrome_path}")

    is_ci = os.environ.get('GITHUB_ACTIONS') == 'true'
    user_data_dir = os.path.join(os.getcwd(), 'chrome_user_data_ci' if (headless or is_ci) else 'chrome_user_data')

    for attempt in range(1, max_retries + 1):
        print(f"\n--- 第 {attempt} 次尝试登录 ---")
        co = ChromiumOptions()
        co.set_paths(browser_path=chrome_path)

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

        page = None
        try:
            page = ChromiumPage(co)
            print("✅ 浏览器启动成功")
        except Exception as e:
            print(f"❌ 浏览器启动失败: {e}")
            if headless or is_ci:
                # 降级为非无头模式（auto_port）
                co = ChromiumOptions()
                co.set_paths(browser_path=chrome_path)
                co.auto_port(True)
                co.set_argument('--window-size=1920,1080')
                co.set_argument('--no-sandbox')
                co.set_argument('--disable-gpu')
                co.set_argument('--disable-dev-shm-usage')
                page = ChromiumPage(co)
                print("✅ 已切换到非无头模式启动（auto_port）")
            else:
                raise

        try:
            # ==================== 登录交互（完全保留原样） ====================
            login_url = 'https://of.swu.edu.cn/cas/oauth/login/SWU_CAS2_FEDERAL?service=https%3A%2F%2Fof.swu.edu.cn%2Fgateway%2Ffighter-middle%2Fapi%2Fintegrate%2Fuaap%2Fcas%2Fresolve-cas-return%3Fnext%3Dhttps%253A%252F%252Fof.swu.edu.cn%252F%2523%252FcasLogin%253Ffrom%253D%25252FappCenter'
            page.get(login_url)
            print(f"当前页面标题: {page.title}")
            print(f"当前URL: {page.url}")

            unified_btn = page.ele('@src=img/unified_button.png', timeout=5)
            if unified_btn:
                unified_btn.click()
                print("已点击统一认证按钮，等待跳转...")
                time.sleep(3)
                print(f"跳转后标题: {page.title}")
                print(f"跳转后URL: {page.url}")

            print("等待登录表单加载...")
            time.sleep(1)

            iframes = page.eles('tag:iframe', timeout=3)
            if iframes:
                print(f"发现 {len(iframes)} 个 iframe，尝试切换到第一个")
                page.to_frame(iframes[0])
                time.sleep(1)

            username_input = page.ele('@name=username', timeout=3) or page.ele('@name=j_username', timeout=3)
            if not username_input:
                inputs = page.eles('tag:input@type=text', timeout=3)
                if inputs:
                    username_input = inputs[0]
            if not username_input:
                raise Exception("❌ 未找到用户名输入框")
            username_input.clear().input(username)
            print("✅ 已输入用户名")

            password_input = page.ele('@name=password', timeout=3) or page.ele('@name=j_password', timeout=3)
            if not password_input:
                inputs = page.eles('tag:input@type=password', timeout=3)
                if inputs:
                    password_input = inputs[0]
            if not password_input:
                raise Exception("❌ 未找到密码输入框")
            password_input.clear().input(password)
            print("✅ 已输入密码")

            print("正在获取验证码...")
            time.sleep(0.5)
            img = page.ele('@id=kaptchaImage', timeout=5) or page.ele('@src=/am/validate.code', timeout=5)
            if not img:
                all_imgs = page.eles('tag:img', timeout=3)
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

            captcha_input = page.ele('@name=captcha', timeout=3) or page.ele('@name=verificationCode', timeout=3)
            if not captcha_input:
                inputs = page.eles('tag:input@type=text', timeout=3)
                if inputs:
                    if len(inputs) > 1:
                        captcha_input = inputs[-1]
                    else:
                        captcha_input = inputs[0]
            if not captcha_input:
                captcha_input = page.ele('xpath://input[@type="text"][position()>2]', timeout=3)
            if not captcha_input:
                raise Exception("❌ 未找到验证码输入框")

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

            login_btn = page.ele('@style=vertical-align: top;', timeout=3)
            if not login_btn:
                login_btn = page.ele('.btn.btn-default.blue', timeout=3)
            if not login_btn:
                login_btn = page.ele('tag:input@type=submit', timeout=3)
            if not login_btn:
                login_btn = page.ele('text=登录', timeout=3)
            if not login_btn:
                raise Exception("❌ 未找到登录按钮")

            page.actions.move_to(login_btn).click().wait(0.5)
            print("✅ 已点击登录按钮")

            time.sleep(3)
            error_msgs = page.eles('.error, #err, .msg-error, .alert-danger', timeout=1)
            if error_msgs:
                for e in error_msgs:
                    print(f"⚠️ 错误信息: {e.text}")
                raise Exception(f"登录失败: {error_msgs[0].text}")

            # ==================== token 提取（优化版：高稳定、高速度） ====================
            print("等待登录成功后跳转...")
            start_time = time.time()
            timeout = 20
            wait_interval = 0.2
            entered_target = False
            token = None

            while time.time() - start_time < timeout:
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
                            # 使用浏览器 fetch 验证，避免引入 requests 指纹
                            js_check = f'''
                                return fetch("{test_url}", {{
                                    headers: {{"fighter-auth-token": "{token}"}}
                                }}).then(r => r.ok);
                            '''
                            ok = page.run_js(js_check)
                            if ok:
                                print("✅ localStorage 中的 token 有效")
                                # 清理临时验证码图片
                                if os.path.exists(file_path):
                                    os.remove(file_path)
                                    try:
                                        os.rmdir('images')
                                    except:
                                        pass
                                # 此时返回 page 和 token，不关闭浏览器
                                return page, token
                            else:
                                print("⚠️ localStorage 中的 token 无效，继续等待...")
                                token = None
                        except Exception as e:
                            print(f"⚠️ 验证 token 时发生异常: {e}")
                            token = None
                else:
                    if entered_target:
                        entered_target = False

                elapsed = time.time() - start_time
                if int(elapsed) % 5 == 0:
                    print(f"⏳ 已等待 {elapsed:.0f}s，当前 URL: {current_url[:80]}...")

                time.sleep(wait_interval)

            raise Exception("获取 token 超时（20s），未从 localStorage 获取到有效 access_token")

        except Exception as e:
            print(f"第 {attempt} 次尝试失败: {e}")
            if os.path.exists('images/captcha.png'):
                os.remove('images/captcha.png')
                try:
                    os.rmdir('images')
                except:
                    pass
            if page:
                try:
                    page.quit()
                except:
                    pass
            # 清理用户数据目录（确保下次运行环境干净）
            if os.path.exists(user_data_dir):
                try:
                    shutil.rmtree(user_data_dir)
                    print(f"✅ 已清除浏览器数据目录: {user_data_dir}")
                except Exception as e:
                    print(f"⚠️ 清除浏览器数据目录失败（可忽略）: {e}")
            if attempt == max_retries:
                raise
            else:
                print("等待 2 秒后重试...")
                time.sleep(2)

    raise Exception(f"登录失败，已重试 {max_retries} 次。")

# ==================== 打卡模块（使用浏览器发起请求） ====================
def get_transition_today(token: str):
    """获取今日任务（仍使用 requests，仅为查询，风险低）"""
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
    """获取学号（仍使用 requests）"""
    url = "https://of.swu.edu.cn/gateway/fighter-middle/api/auth/user?appType=fighter-portal"
    headers = {"fighter-auth-token": token}
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        raise Exception(f"获取学号失败，HTTP状态码: {resp.status_code}")
    return resp.json()["data"]["subject"]["username"]

def checkin_with_page(page, token: str):
    """
    使用浏览器页面提交打卡（全程同一浏览器，UA一致）
    """
    try:
        task = get_transition_today(token)
        if not task:
            msg = "今日无打卡任务"
            print(f"ℹ️ {msg}")
            return True, msg, 10

        if task.get("qdzt") == "已签到":
            msg = "今日已签到，无需重复"
            print(f"✅ {msg}")
            return True, msg, 0

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

        # 通过浏览器的 fetch 提交，保证 TLS/UA 和登录时一致
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
            msg = f"打卡提交异常: {result['error']}"
            print(f"❌ {msg}")
            return False, msg, 20

        if result.get("code") == 200 and result.get("data"):
            msg = "打卡成功！"
            print(f"✅ {msg}")
            return True, msg, 0
        else:
            msg = f"打卡失败: {result.get('msg', '未知错误')}"
            print(f"❌ {msg}")
            return False, msg, 20

    except Exception as e:
        msg = f"打卡过程中异常: {e}"
        print(f"❌ {msg}")
        return False, msg, 20

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

    token = MANUAL_TOKEN.strip()
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
    if page:
        # 使用浏览器提交
        success, reason, exit_code = checkin_with_page(page, token)
    else:
        # 手动 token 时，无浏览器，退化为 requests 方式（保留原函数）
        # 但为了保持一致性，也可调用原 checkin 函数，但这里我们复用原逻辑
        # 简单起见，直接调用原 checkin（但已删除，需要重新定义？）
        # 为了兼容手动 token，我们保留原来的 requests 提交函数，但因为我们修改了结构，下面临时实现
        # 其实可以写一个 fallback 用 requests 提交，但鉴于用户主要使用自动登录，我们可简单处理
        # 这里提供一个简化的 requests 提交（复用原有逻辑）
        def fallback_checkin(token):
            # 原 checkin 逻辑（使用 requests）
            try:
                task = get_transition_today(token)
                if not task:
                    return True, "今日无打卡任务", 10
                if task.get("qdzt") == "已签到":
                    return True, "今日已签到，无需重复", 0
                student_id = get_student_id(token)
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
                    return True, "打卡成功！", 0
                else:
                    return False, f"打卡失败: {data.get('msg', '未知错误')}", 20
            except Exception as e:
                return False, f"异常: {e}", 20

        success, reason, exit_code = fallback_checkin(token)

    # 清理浏览器资源（如果存在）
    if page:
        try:
            page.quit()
            print("✅ 浏览器已关闭")
        except:
            pass
        # 清理用户数据目录
        is_ci = os.environ.get('GITHUB_ACTIONS') == 'true'
        user_data_dir = os.path.join(os.getcwd(), 'chrome_user_data_ci' if (headless_mode or is_ci) else 'chrome_user_data')
        if os.path.exists(user_data_dir):
            try:
                shutil.rmtree(user_data_dir)
                print(f"✅ 已清除浏览器数据目录: {user_data_dir}")
            except Exception as e:
                print(f"⚠️ 清除浏览器数据目录失败（可忽略）: {e}")

    if success:
        print(f"✅ 打卡流程完成：{reason}")
        sys.exit(0)
    else:
        print(f"❌ 打卡失败：{reason}")
        sys.exit(1)

if __name__ == "__main__":
    main()
