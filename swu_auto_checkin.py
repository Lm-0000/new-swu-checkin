#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import json
import subprocess
import tempfile
import re
import ddddocr
import requests
from DrissionPage import ChromiumPage, ChromiumOptions

MAX_RETRY = 3

def _start_chrome_and_get_debug_url() -> str:
    """手动启动 Chrome 并返回 DevTools 调试地址"""
    chrome_path = os.environ.get('CHROME_PATH', 'google-chrome')
    user_data_dir = tempfile.mkdtemp()
    
    # 选择一个固定端口，避免冲突
    debug_port = 9222
    cmd = [
        chrome_path,
        f'--remote-debugging-port={debug_port}',
        f'--user-data-dir={user_data_dir}',
        '--no-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
        '--disable-setuid-sandbox',
        '--headless=new',  # 新版无头模式，兼容 GitHub Actions
        '--window-size=1920,1080',
        '--disable-blink-features=AutomationControlled',
        'about:blank'
    ]
    # 启动浏览器，捕获 stderr，因为 DevTools 监听地址通常输出到 stderr
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    # 等待输出调试地址（最多 10 秒）
    start_time = time.time()
    debug_url = None
    while time.time() - start_time < 10:
        line = proc.stderr.readline()
        if not line:
            time.sleep(0.1)
            continue
        # 查找 DevTools listening on ws://... 行
        match = re.search(r'DevTools listening on (ws://\S+)', line)
        if match:
            debug_url = match.group(1)
            break
    if not debug_url:
        proc.kill()
        raise Exception("无法获取 Chrome DevTools 调试地址")
    return debug_url

def get_swu_token(username: str, password: str) -> str:
    """DrissionPage 登录，通过手动启动浏览器绕过地址解析错误"""
    last_exception = None
    file_path = None
    for attempt in range(1, MAX_RETRY + 1):
        dp = None
        browser_proc = None
        try:
            # 手动启动浏览器并获取调试地址
            debug_url = _start_chrome_and_get_debug_url()
            print(f"Chrome 调试地址: {debug_url}")

            # 配置 DrissionPage 连接该地址
            co = ChromiumOptions()
            co.set_browser_path(os.environ.get('CHROME_PATH'))  # 实际上已不需要，但保留以防万一
            # 关键：直接设置地址，让 DrissionPage 连接已有浏览器
            co.set_address(debug_url.replace('ws://', '').replace('/devtools/browser', ''))
            # 注意：set_address 期望 'ip:port' 格式
            address = debug_url.replace('ws://', '').split('/')[0]  # 得到 '127.0.0.1:9222'
            co.set_address(address)

            dp = ChromiumPage(co)
            login_url = (
                'https://of.swu.edu.cn/cas/oauth/login/SWU_CAS2_FEDERAL'
                '?service=https%3A%2F%2Fof.swu.edu.cn%2Fgateway%2Ffighter-middle'
                '%2Fapi%2Fintegrate%2Fuaap%2Fcas%2Fresolve-cas-return'
                '%3Fnext%3Dhttps%253A%252F%252Fof.swu.edu.cn%252F%2523%252FcasLogin'
                '%253Ffrom%253D%25252FappCenter'
            )
            dp.get(login_url)

            # 1. 点击统一身份认证按钮
            unified_btn = dp.ele('#loginTypeBox div[onclick="_goLogin()"]', timeout=5)
            if not unified_btn:
                unified_btn = dp.ele('@src=img/unified_button.png', timeout=5)
            if unified_btn:
                unified_btn.click()
                time.sleep(2)

            # 2. 输入账号密码
            username_input = dp.ele('#loginName', timeout=5)
            if not username_input:
                username_input = dp.ele('@class=hd', index=1, timeout=5)
            password_input = dp.ele('#password', timeout=5)
            if not password_input:
                password_input = dp.ele('@class=hd', index=2, timeout=5)
            if not username_input or not password_input:
                raise Exception("未找到用户名或密码输入框")
            username_input.clear().input(username)
            password_input.clear().input(password)

            # 3. 验证码处理
            os.makedirs('images', exist_ok=True)
            img = dp.ele('#kaptchaImage', timeout=5)
            if not img:
                img = dp.ele('@src=validate', timeout=5)
            if not img:
                raise Exception("未找到验证码图片")
            file_path = 'images/captcha.png'
            if os.path.exists(file_path):
                os.remove(file_path)
            img.save(path='images', name='captcha.png')

            with open(file_path, 'rb') as f:
                image_bytes = f.read()
            ocr = ddddocr.DdddOcr(show_ad=False)
            result = ocr.classification(image_bytes)
            print(f"[尝试 {attempt}/{MAX_RETRY}] 识别验证码: {result}")

            # 4. 输入验证码并触发事件
            captcha_input = dp.ele('@class=dfinput', timeout=3)
            if not captcha_input:
                captcha_input = dp.eles('tag=input@@type=text')[-1]
            captcha_input.clear()
            dp.actions.click(captcha_input).type(result)
            dp.run_js('''
                var el = arguments[0];
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: true }));
            ''', captcha_input)
            time.sleep(0.3)

            # 5. 点击登录按钮
            login_btn = dp.ele('@style=vertical-align: top;', timeout=5)
            if not login_btn:
                login_btn = dp.ele('.btn.btn-default.blue', timeout=5)
            if not login_btn:
                login_btn = dp.ele('tag=input@@type=submit', timeout=5)
            if not login_btn:
                raise Exception("未找到登录按钮")
            login_btn.click()

            print("等待页面跳转加载...")
            time.sleep(8)

            # 6. 获取 token
            print("等待登录完成并获取 token...")
            for _ in range(30):
                time.sleep(1)
                try:
                    token = dp.run_js('return localStorage.getItem("access_token") || sessionStorage.getItem("access_token")')
                    if token:
                        return token
                except Exception as e:
                    print(f"读取 token 时异常: {e}")
                err = dp.ele('#err', timeout=0.2)
                if err and ('验证码错误' in err.text or '验证码不正确' in err.text):
                    print("验证码错误，准备重试...")
                    break
            else:
                raise Exception("获取 token 超时，可能登录失败")

        except Exception as e:
            last_exception = e
            print(f"第 {attempt} 次尝试失败: {e}")
            if attempt < MAX_RETRY:
                time.sleep(2)
        finally:
            if dp:
                dp.quit()
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                try:
                    os.rmdir('images')
                except OSError:
                    pass

    raise Exception(f"所有重试均失败，最后错误: {last_exception}")


def get_transition_today(token: str):
    url = "https://of.swu.edu.cn/gateway/fighter-baida/api/cqtj/getTransitionByToday"
    headers = {"fighter-auth-token": token}
    resp = requests.post(url, headers=headers, data={"pageNum": 1, "pageSize": 1}).json()
    records = resp.get("data", {}).get("records", [])
    return records[0] if records else None


def get_student_id(token: str):
    url = "https://of.swu.edu.cn/gateway/fighter-middle/api/auth/user?appType=fighter-portal"
    headers = {"fighter-auth-token": token}
    resp = requests.get(url, headers=headers).json()
    return resp["data"]["subject"]["username"]


def checkin(token: str):
    task = get_transition_today(token)
    if not task:
        print("❌ 今日无打卡任务")
        return False
    if task.get("qdzt") == "已签到":
        print("✅ 今日已打卡，无需重复操作")
        return True

    student_id = get_student_id(token)
    formid = task["formId"]
    record_id = task["id"]
    url = "https://of.swu.edu.cn/gateway/fighter-baida/api/form-instance/save"
    params = {"formId": formid, "isSubmitProcess": False}
    headers = {"fighter-auth-token": token, "Content-Type": "application/json"}
    payload = {
        "id": record_id,
        "formId": formid,
        "tsrq": time.strftime("%Y-%m-%d"),
        "xh": student_id,
        "qdsj": ["21:00", "23:30"],
    }
    resp = requests.post(url, headers=headers, params=params, data=json.dumps(payload)).json()
    if resp.get("code") == 200 and resp.get("data"):
        print("✅ 打卡成功！")
        return True
    else:
        print(f"❌ 打卡失败: {resp.get('msg', '未知错误')}")
        return False


def main():
    username = os.environ.get("SWU_USERNAME")
    password = os.environ.get("SWU_PASSWORD")
    if not username or not password:
        print("❌ 缺少环境变量 SWU_USERNAME 或 SWU_PASSWORD")
        raise SystemExit(1)

    try:
        print("开始自动登录获取 token...")
        token = get_swu_token(username, password)
        print(f"获取 token 成功: {token[:10]}...")
        print("正在执行打卡...")
        success = checkin(token)
        if not success:
            raise SystemExit(1)
    except Exception as e:
        print(f"❌ 运行失败: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
