import json
import random
import requests
import subprocess
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')

NUMBER_OF_NODE_GROUP_MEMBERS = 50
'''节点延迟测试时，节点数量过多时就需要分组请求，每一组的节点数量上限'''
RANDOM_SELECTED_NODE = False
'''为端口选择节点是否随机'''
NODE_NAME_BLACKLIST = []
'''节点名黑名单，涉及到的节点不参与延迟测试'''
NODE_PROTOCOL_BLACKLIST = []
'''节点协议黑名单，涉及到的节点不参与延迟测试'''
CONFIG = {}
V2RAYA_CONTAINER_NAME = "v2rayA"
FORCED_RESET_PROXY = True
HOST = ""
TOKEN = ""
PROXY_HOST = ""
V2RAYA_CONFIG = ""

def load_config():
    global CONFIG, V2RAYA_CONTAINER_NAME, FORCED_RESET_PROXY, HOST, NUMBER_OF_NODE_GROUP_MEMBERS, RANDOM_SELECTED_NODE, NODE_NAME_BLACKLIST, NODE_PROTOCOL_BLACKLIST, PROXY_HOST, V2RAYA_CONFIG
    with open("config.json", "r", encoding='utf8') as f:CONFIG = json.load(f)
    HOST = f"http://{get_container_ip(CONFIG['v2raya_container_name'])}:{CONFIG['webui_port']}"
    FORCED_RESET_PROXY = CONFIG['forced_reset_proxy']
    NUMBER_OF_NODE_GROUP_MEMBERS = CONFIG['number_of_node_group_members']
    RANDOM_SELECTED_NODE = CONFIG['random_selected_node']
    NODE_NAME_BLACKLIST = CONFIG['node_name_blacklist']
    NODE_PROTOCOL_BLACKLIST = CONFIG['node_protocol_blacklist']
    PROXY_HOST = get_container_ip(CONFIG['v2raya_container_name'])
    V2RAYA_CONFIG = CONFIG['v2raya_config']

def get_container_ip(container_name):
    '''获取容器的IP地址'''
    try:
        # 获取容器的详细信息
        result = subprocess.run(
            ["docker", "inspect", container_name],
            capture_output=True,
            text=True,
            check=True
        )

        # 解析 JSON 输出
        inspect_output = json.loads(result.stdout)

        # 获取容器的 IP 地址
        ip_address = inspect_output[0]['NetworkSettings']['Networks'].get('1panel-network',{}).get('IPAddress','localhost')

        return ip_address
    except subprocess.CalledProcessError as e:
        logging.info(f"Error inspecting container: {e}")
        return 'localhost'


def check_port():
    '''代理端口可用测试
    返回值
    0: 代理端口可用
    1: 有代理端口不可用
    '''
    def get_ip(proxies=None):
        try:
            response = requests.get("http://myip.ipip.net/", proxies=proxies, timeout=10)
            if response.status_code == 200:return 0
            else:return 1
        except requests.exceptions.ReadTimeout:return 1

    def get_v2raya_config():
        with open(V2RAYA_CONFIG, "r") as f:
            return json.load(f)

    v2rayA_config = get_v2raya_config()
    httpProxyPorts = [inbound["port"] for inbound in v2rayA_config["inbounds"] if inbound["protocol"] == "http"]
    for port in httpProxyPorts:
        proxies = {"http": f"http://{PROXY_HOST}:{port}","https": f"http://{PROXY_HOST}:{port}"}
        result = get_ip(proxies)
        if result == 1:return 1
    return 0

def login():
    global TOKEN
    url = f"{HOST}/api/login"
    payload = {"username": CONFIG['username'],"password": CONFIG['password']}
    headers = {"content-type": "application/json"}
    response = requests.post(url, json=payload, headers=headers)
    TOKEN = response.json()["data"]["token"]

def get_status():
    '''获取服务状态'''
    url = f"{HOST}/api/touch"
    response = requests.get(url, headers={"Authorization": TOKEN})
    return response.json()

def get_outbounds():
    '''获取出站'''
    url = f"{HOST}/api/outbounds"
    response = requests.get(url, headers={"Authorization": TOKEN})
    return response.json()["data"]["outbounds"]

def disable_Proxy():
    return requests.delete(f"{HOST}/api/v2ray", headers={"Authorization": TOKEN}).json()["code"]

def enable_Proxy():
    return requests.post(f"{HOST}/api/v2ray", headers={"Authorization": TOKEN}).json()["code"]

def bulid_request_body(node_ids,sub_num) -> list:
    '''构建请求体, NUMBER_OF_NODE_GROUP_MEMBERS 个节点为一组, 以测试节点延迟'''
    sub_id = int(sub_num) - 1
    _nodes = []
    for i in node_ids:
        _nodes.append({"id": i,"_type": "subscriptionServer","sub": sub_id})
    # 分割 nodes 列表， NUMBER_OF_NODE_GROUP_MEMBERS 为一组
    _nodes = [_nodes[i:i+NUMBER_OF_NODE_GROUP_MEMBERS] for i in range(0, len(_nodes), NUMBER_OF_NODE_GROUP_MEMBERS)]
    nodes = [json.dumps(group).replace("'", '"') for group in _nodes]
    return nodes

def test_httpLatency(nodes):
    '''测试节点延迟'''
    logging.info(f"开始测试节点延迟, 节点共 {len(nodes)} 组, 每组节点数量上限为 {NUMBER_OF_NODE_GROUP_MEMBERS}")
    num = 1
    timestamp = int(time.time())
    start_time = timestamp
    for str_nodes in nodes:
        response = requests.get(f"{HOST}/api/httpLatency?whiches={str_nodes}", headers={"Authorization": TOKEN})
        logging.info(f"进度 {num}/{len(nodes)} , 本组耗时 {int(time.time()) - timestamp} 秒")
        num += 1
        timestamp = int(time.time())
    logging.info(f"测试节点延迟完成, 共耗时 {int(time.time()) - start_time} 秒")

def connect_on(nodes_id, outbounds, status,sub_num):
    '''为出站连接节点
    传入参数: nodes_id - 节点id, outbounds - 出站列表, status - 当前服务状态
    '''
    sub_id = int(sub_num) - 1
    for sub in status["data"]["touch"]["subscriptions"]:
        if sub["id"] == int(sub_num):sub_nodes_info = sub["servers"]
    for num in range(0,len(nodes_id)):
        for outbound in outbounds:
            url = f"{HOST}/api/connection"
            try:node_id = nodes_id[num]
            except IndexError:node_id = nodes_id[0]
            
            payload = {
                        "id": node_id,
                        "_type": "subscriptionServer",
                        "sub": sub_id,
                        "outbound": outbound
                    }
            requests.post(url, json=payload, headers={"Authorization": TOKEN, "content-type": "application/json"})
            for node in sub_nodes_info:
                if node["id"] == node_id:node_info = node 
            logging.info(f"为出站 {outbound} 连接节点 {node_info.get('name')}, 延迟 {node_info.get('pingLatency')}")


def connect_cancel(connect):
    '''取消节点的连接'''
    url = f"{HOST}/api/connection"
    requests.delete(url, json=connect, headers={"Authorization": TOKEN, "content-type": "application/json"})

def nodes_filter(status, outbounds_num,sub_num) -> list:
    '''筛选节点, 传入当前服务状态和出站数量, 返回筛选后的节点列表'''
    sub_id=sub_num
    for sub in status["data"]["touch"]["subscriptions"]:
        if sub["id"] == int(sub_id):nodes = sub["servers"]
    healthy_nodes = []
    for node in nodes:
        if "ms" in node["pingLatency"]:
            healthy_nodes.append(node)

            
    logging.info(f"共有 {len(healthy_nodes)} 个节点")
    for node in healthy_nodes:
        # 字符替换, node["pingLatency"] 的值去掉 "ms" 字符
        node["pingLatency"] = int(node["pingLatency"].replace("ms", ""))
    if RANDOM_SELECTED_NODE:
        # healthy_nodes 随机排序
        random.shuffle(healthy_nodes)
    else:
        # 根据 pingLatency ping的结果由小到大排序
        healthy_nodes.sort(key=lambda x: x["pingLatency"])
    return [node["id"] for node in healthy_nodes]

def test_nodes(sub_num):
    '''测试节点'''
    # 获取服务状态
    status = get_status()
    # 获取订阅的节点延迟
    sub_id = sub_num
    for sub in status["data"]["touch"]["subscriptions"]:
        if sub["id"] == sub_id:
            node_num = len(sub["servers"])
            sub_name = sub.get("remarks", f"ID: {sub['id']}, host: {sub['host']}")
            node_ids = [node["id"] for node in sub["servers"]]
            for i in NODE_NAME_BLACKLIST:
                # 如果节点名称中包含黑名单中的字符, 则从测试延迟的节点列表中移除
                for node in sub["servers"]:
                    if i in node["name"]:node_ids.remove(node["id"])
            for node in sub["servers"]:
                if node["net"] in NODE_PROTOCOL_BLACKLIST:node_ids.remove(node["id"])
    msg = f" , 排除了 {node_num - len(node_ids)} 个节点, 实际 {len(node_ids)} 个节点" if len(node_ids) < node_num else ""
    logging.info(f"准备测试节点延迟, 本次选择的订阅为 {sub_name} , 节点数量为 {node_num}{msg}")
    test_httpLatency(bulid_request_body(node_ids,sub_id))

def reset_proxy(sub_num):
    outbounds = get_outbounds()
    status = get_status() # 获取服务状态
    good_nodes_id = nodes_filter(status, len(outbounds),sub_num)
    # 如果代理开启, 则停用代理
    start_time = int(time.time())
    if status["data"]["running"]:
        msg = "重启代理"
        logging.info(f"停用代理: {disable_Proxy()}")
    else:
        msg = "启动代理"
        logging.info("当前代理停用状态")

    if len(good_nodes_id) > 0:
        connect_on(good_nodes_id, outbounds, status,sub_num)
        logging.info(f"启动代理: {enable_Proxy()}")
        end_time = int(time.time())
        logging.info(f"{msg} 耗时 {end_time - start_time} 秒")
    else:logging.info("没有可用的节点")

def main(sub_num):
    load_config()
    reset_switch = 1 if FORCED_RESET_PROXY else check_port()
    if reset_switch == 1:
        # login()
        test_nodes(sub_num)
    elif reset_switch == 0:logging.info("无异常端口")
    while reset_switch == 1:
        reset_proxy(sub_num)
        reset_switch = check_port()
        if reset_switch == 1:logging.info("有端口出错, 重新设置代理")

if __name__ == "__main__":
    load_config()
    login()
    status = get_status() # 获取服务状态
    connectedServer = status["data"]["touch"]["connectedServer"]    # 获取连接的服务器
    if connectedServer: # 如果有连接的节点
        for connect in connectedServer:
            print(f"start to cancel {connect}")
            connect_cancel(connect)  # 则都取消

    for sub_num in range(1,int(CONFIG["apply_subscription_id"])+1):
        try:
            main(sub_num)
        except:
            print(f"There is no {sub_num},skip......")
