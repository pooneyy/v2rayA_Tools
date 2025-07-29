import json
import random
import re
import requests
import subprocess
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')

APPLY_SUBSCRIPTION_IDS = []
'''应用的订阅的id，每次只会测试该列表中的订阅的节点'''
NUMBER_OF_NODE_GROUP_MEMBERS = 50
'''节点延迟测试时，节点数量过多时就需要分组请求，每一组的节点数量上限'''
RANDOM_SELECTED_NODE = False
'''为端口选择节点是否随机'''
NODE_NAME_BLACKLIST = []
'''节点名黑名单，涉及到的节点不参与延迟测试'''
NODE_PROTOCOL_BLACKLIST = []
'''节点协议黑名单，涉及到的节点不参与延迟测试'''
NODE_DELAY_LIMIT = 0
'''节点延迟上限，超过该值的节点不被选择'''
CONFIG = {}
V2RAYA_CONTAINER_NAME = "v2rayA"
FORCED_RESET_PROXY = True
HOST = ""
TOKEN = ""
PROXY_HOST = ""
V2RAYA_CONFIG = ""

def load_config():
    global CONFIG, V2RAYA_CONTAINER_NAME, FORCED_RESET_PROXY, HOST, APPLY_SUBSCRIPTION_IDS, NUMBER_OF_NODE_GROUP_MEMBERS, RANDOM_SELECTED_NODE, NODE_NAME_BLACKLIST, NODE_PROTOCOL_BLACKLIST, NODE_DELAY_LIMIT, PROXY_HOST, V2RAYA_CONFIG
    with open("config.json", "r", encoding='utf8') as f:CONFIG = json.load(f)
    HOST = f"http://{get_container_ip(CONFIG['v2raya_container_name'])}:{CONFIG['webui_port']}"
    FORCED_RESET_PROXY = CONFIG['forced_reset_proxy']
    APPLY_SUBSCRIPTION_IDS = [int(item) if isinstance(item, str) else item for item in CONFIG["apply_subscription_ids"]]
    NUMBER_OF_NODE_GROUP_MEMBERS = CONFIG['number_of_node_group_members']
    RANDOM_SELECTED_NODE = CONFIG['random_selected_node']
    NODE_NAME_BLACKLIST = CONFIG['node_name_blacklist']
    NODE_PROTOCOL_BLACKLIST = CONFIG['node_protocol_blacklist']
    NODE_DELAY_LIMIT = CONFIG['node_delay_limit']
    PROXY_HOST = get_container_ip(CONFIG['v2raya_container_name'])
    V2RAYA_CONFIG = CONFIG['v2raya_config']

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
        except IOError:return 1

    def get_v2raya_config():
        with open(V2RAYA_CONFIG, "r") as f:
            return json.load(f)

    v2rayA_config = get_v2raya_config()
    httpProxyPorts = [inbound["port"] for inbound in v2rayA_config["inbounds"] if inbound["protocol"] == "http"]
    for port in httpProxyPorts:
        proxies = {"http": f"http://{PROXY_HOST}:{port}","https": f"http://{PROXY_HOST}:{port}"}
        result = get_ip(proxies)
        if result == 1:
            logging.info(f"代理端口 {port} 不可用")
            return 1
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

def bulid_request_body(nodes : dict) -> list:
    '''构建请求体, NUMBER_OF_NODE_GROUP_MEMBERS 个节点为一组, 以测试节点延迟'''
    _nodes = [
        {
            "id": node_id,
            "_type": "server" if sub_id == -1 else "subscriptionServer",
            "sub": None if sub_id == -1 else sub_id - 1
        }
        for sub_id, node_ids in nodes.items()
        for node_id in node_ids
    ]
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

def connect_on(nodes, outbounds):
    '''为出站连接节点
    传入参数: nodes - 节点, outbounds - 出站列表
    '''
    for i, outbound in enumerate(outbounds):
        # 循环选择节点
        node_index = i % len(nodes)
        node = nodes[node_index]
        url = f"{HOST}/api/connection"
        payload = {}
        payload["id"] = node["id"]
        payload["_type"] = node["_type"]
        if node["sub_id"] > 0:payload["sub"] = node["sub_id"] - 1
        payload["outbound"] = outbound
        requests.post(url, json=payload, headers={"Authorization": TOKEN, "content-type": "application/json"})
        logging.info(f"为出站 {outbound} 连接节点 {node.get('name')}, 延迟 {node.get('pingLatency')}")

def connect_cancel(connect):
    '''取消节点的连接'''
    url = f"{HOST}/api/connection"
    requests.delete(url, json=connect, headers={"Authorization": TOKEN, "content-type": "application/json"})

def get_healthy_nodes(status):
    '''获取健康节点'''
    try:
        nodes = []
        healthy_nodes = []
        nodes.extend(status["data"]["touch"]["servers"])
        for sub in status["data"]["touch"]["subscriptions"]:
            if sub["id"] in APPLY_SUBSCRIPTION_IDS:nodes.extend(sub["servers"])
        for node in nodes:
            if "ms" in node["pingLatency"]:healthy_nodes.append(node)
        return healthy_nodes
    except:
        sleep_time = random.randint(6,60)
        time.sleep(sleep_time)
        return get_healthy_nodes(get_status())

def nodes_filter(status, outbounds_num) -> dict:
    '''筛选节点, 传入当前服务状态和出站数量, 返回筛选后的节点列表'''
    all_nodes = [
        {**node, "sub_id": -1}
        for node in status["data"]["touch"]["servers"]
    ] + [
        {**node, "sub_id": sub["id"]}
        for sub in status["data"]["touch"]["subscriptions"]
        if sub["id"] in APPLY_SUBSCRIPTION_IDS
        for node in sub["servers"]
    ]
    usable_nodes = [{**node, "pingLatency": int(node["pingLatency"].replace("ms", ""))} for node in all_nodes if "ms" in node["pingLatency"]]
    # 过滤掉延迟大于上限的节点
    healthy_nodes = [node for node in usable_nodes if node["pingLatency"] <= NODE_DELAY_LIMIT] if NODE_DELAY_LIMIT > 0 else usable_nodes
    msg = f", 其中 {len(healthy_nodes)} 个节点延迟在 {NODE_DELAY_LIMIT} ms 以下" if NODE_DELAY_LIMIT > 0 else ""
    logging.info(f"共有 {len(usable_nodes)} 个可用的节点{msg}")
    if RANDOM_SELECTED_NODE: 
        # healthy_nodes 随机排序
        random.shuffle(healthy_nodes)
    else:
        # 根据 pingLatency ping的结果由小到大排序
        healthy_nodes.sort(key=lambda x: x["pingLatency"])
    return healthy_nodes[:outbounds_num]

def test_nodes():
    '''测试节点'''
    status = get_status()
    simple_nodes = status["data"]["touch"]["servers"]
    subs = status["data"]["touch"]["subscriptions"]
    nodes = {
        -1: [
            node["id"] for node in simple_nodes
            if not any(i in node["name"] for i in NODE_NAME_BLACKLIST)
            and node["net"] not in NODE_PROTOCOL_BLACKLIST
        ],
        **{
            sub["id"]: [
                node["id"] for node in sub["servers"]
                if not any(i in node["name"] for i in NODE_NAME_BLACKLIST)
                and node["net"] not in NODE_PROTOCOL_BLACKLIST
            ]
            for sub in subs
            if sub["id"] in APPLY_SUBSCRIPTION_IDS
        }
    }
    node_num = len(simple_nodes) + sum(len(sub["servers"]) for sub in subs if sub["id"] in APPLY_SUBSCRIPTION_IDS)
    sub_name = [
        sub.get("remarks", f"ID: {sub['id']}, host: {sub['host']}")
        for sub in subs
        if sub["id"] in APPLY_SUBSCRIPTION_IDS
    ]
    sum_of_nodes = sum(len(i) for i in nodes.values())
    msg = f", 排除了 {node_num - sum_of_nodes} 个节点, 实际 {sum_of_nodes} 个节点" if sum_of_nodes < node_num else ""
    logging.info(f"准备测试节点延迟, 本次选择的订阅为 {', '.join(sub_name)}\n一共 {node_num} 个节点, 包含 {len(simple_nodes)} 个单节点{msg}")
    test_httpLatency(bulid_request_body(nodes))

def reset_proxy():
    outbounds = get_outbounds()
    status = get_status() # 获取服务状态
    good_nodes = nodes_filter(status, len(outbounds))
    # 如果代理开启, 则停用代理
    start_time = int(time.time())
    if status["data"]["running"]:
        msg = "重启代理"
        logging.info(f"停用代理: {disable_Proxy()}")
    else:
        msg = "启动代理"
        logging.info("当前代理停用状态")
    connectedServer = status["data"]["touch"]["connectedServer"]    # 获取连接的服务器
    if connectedServer: # 如果有连接的节点
        for connect in connectedServer:connect_cancel(connect)  # 则都取消
    if len(good_nodes) > 0:
        connect_on(good_nodes, outbounds)
        logging.info(f"启动代理: {enable_Proxy()}")
        end_time = int(time.time())
        logging.info(f"{msg} 耗时 {end_time - start_time} 秒")
        return True
    else:
        logging.info("没有可用的节点")
        return False

def main():
    load_config()
    login()
    reset_switch = 1 if FORCED_RESET_PROXY else check_port()
    if reset_switch == 1:
        test_nodes()
    elif reset_switch == 0:logging.info("无异常端口")
    while reset_switch == 1:
        if get_healthy_nodes(get_status()) == []:test_nodes()
        if not reset_proxy():break
        reset_switch = check_port()
        if reset_switch == 1:logging.info("有端口出错, 重新设置代理")

if __name__ == "__main__":
    main()