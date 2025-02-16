
import base64
import itertools
import json
import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib
import uuid
from copy import deepcopy
from urllib.parse import (parse_qs, parse_qsl, quote, quote_plus, unquote,
                          urldefrag, urlencode, urljoin, urlparse, urlsplit,
                          urlunparse)
import numpy as np
import psutil
import requests
import urllib3
from ruamel import yaml

logging.getLogger("urllib3").setLevel(logging.ERROR)

PROXIES={
    'http': 'socks5h://127.0.0.1:{LOCAL_PORT}',
    'https': 'socks5h://127.0.0.1:{LOCAL_PORT}' 
}

ss_scheme = "ss://"
ssr_scheme = "ssr://"
vmess_scheme = "vmess://"
vless_scheme = "vless://"
trojan_scheme = "trojan://"

proxyScheme = [vmess_scheme, vless_scheme, trojan_scheme, ssr_scheme, ss_scheme]

dns = {
    "dns": {
        "servers": [
            "1.1.1.1",
            "8.8.8.8",
            "8.8.4.4",
            "localhost"
        ]
    }
}

inbounds = {
    "inbounds": [
        {
            "listen": "0.0.0.0",
            "port": 1080,
            "protocol": "socks",
            "tag": "socksinbound",
            "settings": {
                "auth": "noauth",
                "udp": True,
                "ip": "0.0.0.0"
            }
        }
    ]
}

ssOut = {
    "outbounds": [
        {
            "protocol": "shadowsocks",
            "settings": {
                "plugin": "",
                "pluginOpts": "",
                "servers": [
                    {
                        "address": "serveraddr.com", # Server address of Shadowsocks 
                        "method": "aes-128-gcm", # Encryption method of Shadowsocks 
                        #"ota": False, # Whether enable OTA, default is false, we don't recommand enable this as decrepted by Shadowsocks
                        "password": "sspasswd", # Password of Shadowsocks 
                        "port": 1024
                    }
                ]
            }
        }
    ]
}

ssrOut = {
    "outbounds": [
        {
            "protocol": "shadowsocks",
            "settings": {
                "plugin": "shadowsocksr",
                "pluginArgs": [
                ],
                "servers": [
                    {
                        "address": "serveraddr.com",
                        "method": "aes-256-cfb",
                        "password": "sspasswd",
                        "port": 1024
                    }
                ]
            }
        }
    ]
}

vmessOut = {
    "outbounds": [
        {
            "protocol": "vmess",     # Outcoming protocol
            "settings": {
                "vnext": [
                    {
                        "address": "serveraddr.com", # Server address, yoou need to edit this to your own IP address/domian.
                        "port": 16823,  # Server listenning port.
                        "users": [
                            {
                                "id": "b831381d-6324-4d53-ad4f-8cda48b30811"  # UUID, must be as same as server side
                            }
                        ]
                    }
                ]
            },
            "streamSettings": {
                "tlsSettings": {
                    "disableSystemRoot": False,
                    "allowInsecure": True
                },
                "xtlsSettings": {
                    "disableSystemRoot": False
                }
            },
            "mux": {
                "enabled": True,
                "concurrency": 8
            }
        }
    ]
}

trojanOut = {
    "outbounds": [
        {
            "protocol": "trojan",
            "settings": {
                "servers": [
                    {
                        "address": "serveraddr.com",
                        "port": 1234,
                        "password": "myP@5s",
                    }
                ],
            },
            "streamSettings": {
                "network": "tcp",
                "security": "tls",
                "tcpSettings": {
                    "header": {
                        "type": "none"
                    }
                },
                "tlsSettings": {
                    "allowInsecure": True,
                    "serverName": ""
                }
            }
        }
    ]
}

PROXYCHAINS = """
strict_chain
proxy_dns 
remote_dns_subnet 224
tcp_read_time_out 15000
tcp_connect_time_out 8000
localnet 127.0.0.0/255.0.0.0
quiet_mode

[ProxyList]
socks5  127.0.0.1 {LOCAL_PORT}
"""


def finder(cmd, spliter):
    return re.search(f"\s+{spliter}\s+(\S+)", cmd).group(1)


def sslocal2ssURI(cmd):
    # cmd = f"ss-local -s {hostname} -p {port} -l {LOCAL_PORT} -m {method} -k {password} -f ./ss.pid"
    server = finder(cmd, "-s")
    server_port = finder(cmd, "-p")
    method = finder(cmd, "-m")
    password = finder(cmd, "-k")
    msg = f"{method}:{password}@{server}:{server_port}"
    return f"ss://{base64.b64encode(msg.encode('ascii')).decode('ascii')}"


def ssURI2sslocal(ss_url, localPort=1080, file2storePID=""):
    server, server_port, method, password, plugin, plugin_opts, tag = parse_ss_withPlugin(ss_url)
    extended = ''
    if plugin or plugin_opts:
        extended = f" --plugin {plugin} --plugin-opts '{plugin_opts}'"
    cmd = f"ss-local -s {server} -p {server_port} -l {localPort} -m {method} -k '{password}'{extended}"
    if file2storePID:
        cmd += f" -f {file2storePID}"
    return cmd


def checkPatternsInList(lines, patterns=proxyScheme):
    result = []
    for line in lines:
        for pattern in patterns:
            res = re.search(f"(\S*\s+|^)({pattern}\S+)", line)
            if res:
                result.append( res.group(2) )
                break
    return result


def ssConfig2json(ss_url, local_port=1080, configFile='CONFIG.json'):
    # https://manpages.debian.org/testing/shadowsocks-libev/shadowsocks-libev.8.en.html#CONFIG_FILE
    server, server_port, method, password, plugin, plugin_opts, tag = parse_ss_withPlugin(ss_url)
    config = {
        "server" : server, 
        "server_port" : int(server_port), 
        "method" : method, 
        "password" : password, 
        "local_port" : local_port,
        "plugin": plugin,
        "plugin_opts": plugin_opts
    }
    
    with open(configFile, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=4)


def is_json(myjson):
    try:
        json.loads(myjson)
    except ValueError as e:
        return False
    return True


def isValidIP(addr):
    try:
        #ipaddress.ip_address(addr)
        socket.inet_aton(addr) 
    except :
        return False # Not legal
    return True # legal


def getIP(domain):
    try:
        ip = socket.gethostbyname(domain)
        return ip
    except Exception:
        return False


def isBase64(sb):
    # https://stackoverflow.com/questions/12315398
    try:
        if isinstance(sb, str):
            # If there's any unicode here, an exception will be thrown and the function will return false
            sb_bytes = bytes(sb, 'ascii')
        elif isinstance(sb, bytes):
            sb_bytes = sb
        else:
            raise ValueError("Argument must be string or bytes")
        sb_bytes = sb_bytes + b'=' * (-len(sb_bytes) % 4)
        if b"-" in sb_bytes or b"_" in sb_bytes:
            return base64.urlsafe_b64encode(base64.urlsafe_b64decode(sb_bytes)) == sb_bytes
        return base64.b64encode(base64.b64decode(sb_bytes).decode().encode()) == sb_bytes
    except Exception:
        return False


def base64Decode(decodedStr) :
    if "-" in decodedStr or "_" in decodedStr:
         # URL safe : The alphabet uses '-' instead of '+' and '_' instead of '/'.
        return base64.urlsafe_b64decode(decodedStr + "===").decode('utf-8')
    return base64.b64decode(decodedStr + '=' * (-len(decodedStr) % 4)).decode('utf-8')


def is_valid_uuid(val):
    try:
        uuid.UUID(val)
    except ValueError:
        return False
    return True


def generate_uuid(basedata):
    UUID_NAMESPACE = uuid.UUID('00000000-0000-0000-0000-000000000000')
    return str(uuid.uuid5(UUID_NAMESPACE, basedata))


def Create_ss_url(server, server_port, method, password):
    return f"ss://{base64.urlsafe_b64encode((method+':'+password).encode()).decode('utf-8')}@{server}:{server_port}"

def Create_ss_url_withPlugin(server, server_port, method, password, plugin="", plugin_opts="", tag="") :
    extended = ''
    if plugin or plugin_opts:
        extended = f"/?plugin={quote_plus(f'{plugin};{plugin_opts}')}"
    tag = tag if tag else "Woman,Life,Freedom"
    return f"ss://{base64.urlsafe_b64encode((method+':'+password).encode()).decode('utf-8').replace('=','')}@{server}:{server_port}{extended}#{tag}"


def Create_vmess_url(jsonLoad):
    return 'vmess://' + base64.b64encode(json.dumps(jsonLoad, indent=4).encode('utf-8')+b'\n').decode()


def parse_ss(ss_url) :
    # https://github.com/shadowsocks/shadowsocks-org/blob/master/whitepaper/whitepaper.md
    # SS-URI = "ss://" userinfo "@" hostname ":" port ["/"] ["?"plugin] ["#" tag]
    mainPart = ss_url.split("#")[0][5:]
    
    try :
        plugin = mainPart.split("?")[1]
        mainPart = mainPart[:re.search("/\?", mainPart).start()]
    except :
        plugin = ""

    if isBase64(mainPart) :
        mainPart = base64Decode(mainPart)
    else :
        decoded = mainPart[:mainPart.find('@')]
        mainPart = mainPart.replace(decoded, base64Decode(decoded), 1)
    
    method, password , server, server_port = re.search("^(.+?):(.+)@(.+):(\d+)", unquote(mainPart)).groups()
    logging.debug(f"{server}:{server_port} {method} {password} {plugin}")
    return server, server_port, method, password


def parse_ss_withPlugin(ss_url) :
    # https://shadowsocks.org/guide/sip002.html
    mainPart, tag = (ss_url[5:].split("#", 1) + [''])[:2]

    try :
        mainPart, query = mainPart.split("?")
        plugin, plugin_opts = parse_qs(query)['plugin'][0].split(';', 1)
    except :
        plugin, plugin_opts = '', ''

    if mainPart[-1]=='/':
        mainPart = mainPart[:-1]

    if isBase64(mainPart) :
        mainPart = base64Decode(mainPart)
    else :
        decoded = mainPart[:mainPart.find('@')]
        mainPart = mainPart.replace(decoded, base64Decode(decoded), 1)

    method, password , server, server_port = re.search("^(.+?):(.+)@(.+):(\d+)", unquote(mainPart)).groups()

    return server, server_port, method, password, plugin, plugin_opts, unquote(tag)


def parse_ssr(ssr_url) :
    ssr_parsed = {}
    ssr_parsed['address'], ssr_parsed['port'], ssr_parsed['protocol'], ssr_parsed['method'], ssr_parsed['obfs'], etc = base64Decode(ssr_url[6:]).split(':')
    password, pluginArgs = etc.rsplit('/?')
    ssr_parsed['password'] = base64Decode(password)
    ssr_parsed['obfsparam']  = base64Decode(parse_qs(pluginArgs).get('obfsparam',[''])[0])
    ssr_parsed['protoparam'] = base64Decode(parse_qs(pluginArgs).get('protoparam',[''])[0])
    ssr_parsed['remarks'] = base64Decode(parse_qs(pluginArgs).get('remarks',[''])[0])
    ssr_parsed['group'] = base64Decode(parse_qs(pluginArgs).get('group',[''])[0])
    return ssr_parsed


def parseVless(loaded):
    uid, address, port = re.search(f"^(.+)@(.+):(\d+)$", loaded.netloc).groups()
    if address[0] == '[':
        address = address[1:-1]
    queryDict = dict(parse_qsl(loaded.query))
    
    notNone = lambda x: x if x!='none' else ''

    queryDict["protocol"] = loaded.scheme
    queryDict["add"] = address
    queryDict["port"] = port
    queryDict["id"] = uid
    queryDict["net"] = notNone(queryDict.pop("type") if 'type' in queryDict else '')
    queryDict["tls"] = notNone(queryDict.pop("security") if 'security' in queryDict else '')
    
    return json.loads(json.dumps(queryDict))


def parseTrojan(loaded):
    queryDict = dict(parse_qsl(loaded.query))
    if (res := re.search(f"^(.+)@(.+):(\d+)$", loaded.netloc)):
        queryDict['password'], queryDict['address'], queryDict['port'] = res.groups()
    else:
        raise Exception("Wrong Trojan URI") 
    return queryDict


def killProcess(processName, cmdline=None):
    for p in psutil.process_iter(attrs=['pid', 'name']):
        if processName in p.name() and (cmdline is None or cmdline in p.cmdline()):
            for child in p.children():
                os.kill(child.pid, signal.SIGKILL)
            os.kill(p.pid, signal.SIGKILL)


def silentremove(filename):
    try:
        os.remove(filename)
    except OSError:
        pass


def is_tool(name):
    """Check whether `name` is on PATH and marked as executable."""
    return shutil.which(name) is not None


def is_port_in_use(port: int) -> bool:
    # stackoverflow.com/questions/2470971
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0


def is_alive(testDomain, proxy, timeOut=3):  
    try:
        start = time.perf_counter()
        requests.head(  testDomain, 
                        proxies = proxy, 
                        timeout = timeOut, 
                        )
        end = time.perf_counter()
    except Exception as e:
        #logging.error(f"test live with {proxy} failed: {e}")
        return 0
    return ((end - start) * 100).__round__()


def processShadowJson(jsonTxt):
    result = []
    for line in json.loads(jsonTxt):
        method, password , server, server_port  = line['method'], line['password'], line['server'], line['server_port']
        ss = Create_ss_url(server, server_port, method, password)
        result.append(ss)
    return result


def parseContent(content, patterns=proxyScheme):
    newProxy = []
    if is_json(content):
        newProxy = processShadowJson(content)
    else: 
        if isBase64(content):
            lines = base64Decode(content).splitlines()
        else :
            lines = content.splitlines()
        newProxy = checkPatternsInList(lines, patterns)
    return newProxy


def ScrapURL(url, patterns=proxyScheme):
    newProxy = []
    try:
        res = requests.get(url, timeout=4)
    except Exception as e:
        logging.debug("Exception occurred", exc_info=True)
        logging.error(f"Can't reach {url}")
        return newProxy
    
    if (res.status_code//100) == 2:
        newProxy = parseContent(res.text.strip(), patterns)
        logging.info(f"Got {len(newProxy)} new proxy from {url}")
    else:
        logging.error(f"Can't get {url} , status code = {res.status_code}")
    return newProxy


def split2Npart(a, n):
    k, m = divmod(len(a), n)
    return (a[i*k+min(i, m):(i+1)*k+min(i+1, m)] for i in range(n))


def mergeMultiDicts(*dicts):
    result = {}
    for d in dicts:
        if sys.version_info >= (3, 9):
            result |= d
        elif sys.version_info >= (3, 5):
            result = {**result, **d}
        else:
            result.update(d)
    return result


def createShadowConfig(ss_url, port=1080):
    config = deepcopy( mergeMultiDicts(dns, inbounds, ssOut) )
    
    config['inbounds'][0]['port'] = port
    
    server, server_port, method, password, plugin, plugin_opts, tag = parse_ss_withPlugin(ss_url)

    config['outbounds'][0]['settings']['plugin'] = plugin
    config['outbounds'][0]['settings']['pluginOpts'] = plugin_opts
    config['outbounds'][0]['settings']['servers'][0]['address']  = server
    config['outbounds'][0]['settings']['servers'][0]['port']     = int(server_port)
    config['outbounds'][0]['settings']['servers'][0]['method']   = method
    config['outbounds'][0]['settings']['servers'][0]['password'] = password

    return config


def createSsrConfig(ssr_url, localPort=1080):
    config = deepcopy( mergeMultiDicts(dns, inbounds, ssrOut) )
    ssr_parsed = parse_ssr(ssr_url)
    config['inbounds'][0]['port'] = localPort
    config['outbounds'][0]['settings']['servers'][0]['address']  = ssr_parsed['address']
    config['outbounds'][0]['settings']['servers'][0]['port']     = int(ssr_parsed['port'])
    config['outbounds'][0]['settings']['servers'][0]['method']   = ssr_parsed['method']
    config['outbounds'][0]['settings']['servers'][0]['password'] = ssr_parsed['password']
    config['outbounds'][0]['settings']["pluginArgs"].append(f'--obfs={ssr_parsed["obfs"]}')
    config['outbounds'][0]['settings']["pluginArgs"].append(f'--obfs-param={ssr_parsed["obfsparam"]}')
    config['outbounds'][0]['settings']["pluginArgs"].append(f'--protocol={ssr_parsed["protocol"]}')
    config['outbounds'][0]['settings']["pluginArgs"].append(f'--protocol-param={ssr_parsed["protoparam"]}')
    return config


def createVmessConfig(jsonLoad, port=1080):
    config = deepcopy( mergeMultiDicts(dns, inbounds, vmessOut) )

    config['inbounds'][0]['port'] = port

    config['outbounds'][0]["protocol"] = jsonLoad["protocol"] if 'protocol' in jsonLoad else "vmess" # vmess/vless
    config['outbounds'][0]["settings"]["vnext"][0]["address"]  = jsonLoad['add']
    config['outbounds'][0]["settings"]["vnext"][0]["port"]  = int(jsonLoad['port'])

    if is_valid_uuid(jsonLoad['id']) :
        config['outbounds'][0]["settings"]["vnext"][0]["users"][0]["id"] = jsonLoad['id']
    else:
        config['outbounds'][0]["settings"]["vnext"][0]["users"][0]["id"] =  generate_uuid(jsonLoad['id'])

    if 'aid' in jsonLoad and jsonLoad['aid']:
        try:
            config['outbounds'][0]["settings"]["vnext"][0]["users"][0]["alterId"] = int(jsonLoad['aid'])
        except:
            logging.error(f"aid: {jsonLoad['aid']} is not int")

    if 'encryption' in jsonLoad:
        config['outbounds'][0]["settings"]["vnext"][0]["users"][0]["encryption"] = jsonLoad['encryption']
    
    sec = jsonLoad["scy"] if 'scy' in jsonLoad else (jsonLoad['security'] if 'security' in jsonLoad else "auto" )
    if sec!="auto" :
        config['outbounds'][0]["settings"]["vnext"][0]["users"][0]["security"] = sec  # "aes-128-gcm"


    if jsonLoad["net"]=="ws": 
        config['outbounds'][0]["streamSettings"]["network"] = "ws"
        if 'host' in jsonLoad :
            config['outbounds'][0]["streamSettings"]["wsSettings"] = {"headers":{"Host":jsonLoad['host']} ,
                                                                      "connectionReuse": True,
                                                                      "path":jsonLoad['path']}
    elif jsonLoad["net"]=="h2": 
        config['outbounds'][0]["streamSettings"]["network"] = "http"
        config['outbounds'][0]["streamSettings"]["httpSettings"] = {"headers":{"Host":jsonLoad['host']} , 
                                                                    "path":jsonLoad['path']}
    elif jsonLoad["net"]=="grpc": 
        config['outbounds'][0]["streamSettings"]["network"] = "grpc"
        config['outbounds'][0]["streamSettings"]["grpcSettings"] = {"serviceName":jsonLoad['path']}
    elif jsonLoad["net"]=="kcp": 
        config['outbounds'][0]["streamSettings"]["network"] = "kcp"

    if jsonLoad["tls"]:  #   "tls"
        config['outbounds'][0]["streamSettings"]["security"] = jsonLoad["tls"]
    if "skip-cert-verify" in jsonLoad and jsonLoad["skip-cert-verify"]:
        config['outbounds'][0]["streamSettings"]["tlsSettings"] = {"allowInsecure": True}
    
    return config


def createTrojanConfig(loaded, localPort=1080):
    config = deepcopy( mergeMultiDicts(dns, inbounds, trojanOut) )
    
    trojan_parsed = parseTrojan(loaded)
    
    config['inbounds'][0]['port'] = localPort
    
    config['outbounds'][0]['settings']['servers'][0]['address']  = trojan_parsed['address']
    config['outbounds'][0]['settings']['servers'][0]['port']     = int(trojan_parsed['port'])
    config['outbounds'][0]['settings']['servers'][0]['password'] = trojan_parsed['password']
 
    if 'network' in trojan_parsed :
        config['outbounds'][0]['streamSettings']["network"] = trojan_parsed['network']
    if 'security' in trojan_parsed :
        config['outbounds'][0]['streamSettings']["security"] = trojan_parsed['security']
    if 'sni' in trojan_parsed :
        config['outbounds'][0]['streamSettings']['tlsSettings']["serverName"] = trojan_parsed['sni']
    if 'allowInsecure' in trojan_parsed and trojan_parsed['allowInsecure']=='1':
        config['outbounds'][0]['streamSettings']['tlsSettings']["allowInsecure"] = True
        
    return config


def set_proxychains(localPort=1080):
    pchPath = os.path.expanduser('~/.proxychains/proxychains.conf')
    if os.path.exists(pchPath):
        os.system(f"cp {pchPath} {pchPath}.bak")
    with open(pchPath, "w") as f:
        f.write(PROXYCHAINS.format(LOCAL_PORT=localPort))
    logging.info("proxychains.conf updated!")


def set_system_proxy(proxyHost="127.0.0.1", proxyPort=1080, proxyType="socks5", enable=True):
    if os.name == "nt":
        logging.info("Not Implemented for Windows")
        return
    else:
        # export {https,ftp,rsync,all}__proxy=socks5://127.0.0.1:1080
        proxy = f"{proxyType}://{proxyHost}:{proxyPort}"
        all_proxy = f"export all_proxy={proxy}"
        no_proxy = "export no_proxy=localhost,127.0.0.0/8,192.168.0.0/16,::1"
        
        SHELL = os.environ.get('SHELL')
        if "zsh" in SHELL:
            file = "~/.zshrc"
        elif "bash" in SHELL:
            file = "~/.bashrc"
        else:
            logging.error(f"Not supported SHELL: {SHELL}")
            return

        # get current bashrc
        with open(os.path.expanduser(file), "r") as f:
            lines = f.readlines()
        # remove old proxy setting
        lines = [line for line in lines if not line.startswith("export all_proxy=") and not line.startswith("export no_proxy=")]
        if enable:
            lines.append(f"{all_proxy} && {no_proxy}")
        # save to bashrc
        with open(os.path.expanduser(file), "w") as f:
            f.writelines(lines)
        #os.system(f"source {file}")
        logging.info("set proxy done!" if enable else "unset proxy done!")


def installDocker():
    if not is_tool('docker'):
        # Install docker if docker are not installed
        try:
            try:
                logging.info("Docker Not Found.\nInstalling Docker ...")
                subprocess.run("curl https://get.docker.com | sh", shell=True, check=True)
            except subprocess.CalledProcessError:
                sys.exit("Download Failed !")

            # Check if Docker Service are Enabled
            systemctl = subprocess.call(["systemctl", "is-active", "--quiet", "docker"])
            if systemctl:
                subprocess.call(["systemctl", "enable", "--now", "--quiet", "docker"])
            time.sleep(2)
        except subprocess.CalledProcessError as e:
            sys.exit(e)
        except PermissionError:
            sys.exit("ًroot privileges required")
    logging.info("Docker Installed")

