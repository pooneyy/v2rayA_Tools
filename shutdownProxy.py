import json
import re
import requests
import subprocess

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
        print.info(f"Error inspecting container: {e}")
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

def connect_cancel(connect):
    '''取消节点的连接'''
    url = f"{HOST}/api/connection"
    requests.delete(url, json=connect, headers={"Authorization": TOKEN, "content-type": "application/json"})

def main():
    load_config()
    login()
    status = get_status()
    # 如果代理开启, 则停用代理
    if status["data"]["running"]:print(f"停用代理: {disable_Proxy()}")
    else:print("当前代理停用状态")
    connectedServer = status["data"]["touch"]["connectedServer"] # 获取连接的服务器
    if connectedServer: # 如果有连接的节点
        for connect in connectedServer:connect_cancel(connect)  # 则都取消

if __name__ == "__main__":
    main()