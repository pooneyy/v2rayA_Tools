import json
import re
import requests
import subprocess
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')

NUMBER_OF_NODE_GROUP_MEMBERS = 50
'''节点延迟测试时，节点数量过多时就需要分组请求，每一组的节点数量上限'''
CONFIG = {}
HOST = ""
TOKEN = ""
def load_config():
    global CONFIG, HOST, NUMBER_OF_NODE_GROUP_MEMBERS
    with open("config.json", "r", encoding='utf8') as f:CONFIG = json.load(f)
    HOST = f"http://{get_container_ip(CONFIG['v2raya_container_name'])}:{CONFIG['webui_port']}"
    NUMBER_OF_NODE_GROUP_MEMBERS = CONFIG['number_of_node_group_members']

def get_container_ip(container_name):
    '''获取容器的IP地址'''
    try:
        # 获取容器的详细信息
        result = subprocess.run(
            ["docker", "inspect", r"-f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'", container_name],
            capture_output=True,
            text=True,
            check=True
        )
        ip_address = result.stdout.strip()
        ip_match = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', ip_address)
        if ip_match:return ip_match.group(1)
        else:return 'localhost'
    except subprocess.CalledProcessError as e:
        logging.info(f"Error inspecting container: {e}")
        return 'localhost'

def login():
    global TOKEN
    url = f"{HOST}/api/login"
    payload = {"username": CONFIG['username'],"password": CONFIG['password']}
    headers = {"content-type": "application/json"}
    response = requests.post(url, json=payload, headers=headers)
    TOKEN = response.json()["data"]["token"]

def get_status():
    url = f"{HOST}/api/touch"
    response = requests.get(url, headers={"Authorization": TOKEN})
    return response.json()

def disable_Proxy():
    return requests.delete(f"{HOST}/api/v2ray", headers={"Authorization": TOKEN}).json()["code"]

def enable_Proxy():
    return requests.post(f"{HOST}/api/v2ray", headers={"Authorization": TOKEN}).json()["code"]

def updateSub(id):
    url = f"{HOST}/api/subscription"
    payload = {"id": id,"_type": "subscription"}
    headers = {"authorization": TOKEN,"content-type": "application/json"}
    response = requests.request("PUT", url, json=payload, headers=headers)

def main():
    load_config()
    login()
    # 获取服务状态
    status = get_status()
    sub_info = status["data"]["touch"]["subscriptions"]
    applied_sub_ids = CONFIG['apply_subscription_id']
    sub_start_time = int(time.time())
    if status["data"]["running"]:
        logging.info(f"停用代理: {disable_Proxy()}")
        for sub_id in applied_sub_ids:updateSub(sub_id)
        logging.info(f"启用代理: {enable_Proxy()}")
    else:
        for sub_id in applied_sub_ids:updateSub(sub_id)
    sub_end_time = int(time.time())
    logging.info(f'''更新订阅 {', '.join(sub.get("remarks", f"ID: {sub['id']}") for sub in sub_info if sub["id"] in applied_sub_ids)} 耗时 {sub_end_time - sub_start_time} 秒''')

if __name__ == "__main__":
    main()
