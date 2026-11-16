#!/usr/bin/env python3
"""
discover.py — Localiza câmeras/DVRs iCSee/XMeye (Xiongmai) na rede local.

Usa dois métodos complementares:
  1. Broadcast UDP do protocolo de busca DVRIP (porta 34569, msgid 1530).
     O aparelho responde com seu JSON de rede (IP, MAC, portas, nome).
  2. Varredura TCP da porta 34567 na sub-rede (confirma e pega quem não
     respondeu ao broadcast, ex.: em VLAN/roteador que bloqueia broadcast).

Uso:
    python3 discover.py                      # auto: broadcast + scan /24 local
    python3 discover.py --subnet 192.168.1.0/24
    python3 discover.py --no-scan            # só broadcast UDP
    python3 discover.py --timeout 3
"""

import argparse
import concurrent.futures
import ipaddress
import json
import socket
import struct
import sys

DISCOVER_PORT = 34569   # UDP: busca/config
SERVICE_PORT = 34567    # TCP: serviço DVRIP
HEAD_FLAG = 0xFF
OP_SEARCH = 1530        # msgid do pacote de busca


def _build_packet(msgid, payload=b""):
    if isinstance(payload, (dict, list)):
        payload = json.dumps(payload).encode()
    header = struct.pack("<BBxxIIxxHI", HEAD_FLAG, 0, 0, 0, msgid, len(payload))
    return header + payload


def udp_discover(timeout=3.0):
    """Envia broadcast de busca e coleta respostas dos aparelhos."""
    found = {}
    pkt = _build_packet(OP_SEARCH, {})
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        s.bind(("", DISCOVER_PORT))
    except OSError:
        s.bind(("", 0))
    s.settimeout(timeout)

    for dest in ("255.255.255.255", "<broadcast>"):
        try:
            s.sendto(pkt, (dest, DISCOVER_PORT))
        except OSError:
            pass

    import time
    end = time.time() + timeout
    while time.time() < end:
        try:
            data, addr = s.recvfrom(65535)
        except socket.timeout:
            break
        except OSError:
            break
        info = _parse_response(data)
        if info is not None:
            key = info.get("HostIP") or addr[0]
            found[key] = info
    s.close()
    return found


def _parse_response(data):
    if len(data) < 20 or data[0] != HEAD_FLAG:
        return None
    body = data[20:].split(b"\x00", 1)[0].strip()
    try:
        obj = json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return None
    net = obj.get("NetWork.NetCommon") or obj.get("NetWork") or obj
    # Normaliza hex -> IP legível quando vier como 0x.......
    def hx2ip(v):
        if isinstance(v, str) and v.startswith("0x"):
            n = int(v, 16)
            return ".".join(str((n >> (8 * i)) & 0xFF) for i in (0, 1, 2, 3))
        return v
    for k in ("HostIP", "GateWay", "Submask"):
        if k in net:
            net[k] = hx2ip(net[k])
    return net


def tcp_probe(ip, timeout=0.6):
    try:
        with socket.create_connection((ip, SERVICE_PORT), timeout):
            return ip
    except OSError:
        return None


def scan_subnet(subnet, timeout=0.6, workers=128):
    net = ipaddress.ip_network(subnet, strict=False)
    hosts = [str(h) for h in net.hosts()]
    alive = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(lambda ip: tcp_probe(ip, timeout), hosts):
            if r:
                alive.append(r)
    return alive


def default_subnet():
    """Descobre a sub-rede da interface que alcança a internet."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    finally:
        s.close()
    return f"{ip}/24"


def main(argv=None):
    p = argparse.ArgumentParser(description="Localiza câmeras iCSee/XMeye na LAN.")
    p.add_argument("--subnet", help="ex.: 192.168.1.0/24 (padrão: auto)")
    p.add_argument("--timeout", type=float, default=3.0, help="timeout do broadcast")
    p.add_argument("--scan-timeout", type=float, default=0.6)
    p.add_argument("--no-scan", action="store_true", help="só broadcast UDP")
    p.add_argument("--no-broadcast", action="store_true", help="só varredura TCP")
    args = p.parse_args(argv)

    results = {}

    if not args.no_broadcast:
        print(f"[*] Broadcast de busca DVRIP (UDP {DISCOVER_PORT})...",
              file=sys.stderr)
        try:
            for ip, info in udp_discover(args.timeout).items():
                results[ip] = info
        except Exception as e:
            print(f"    (broadcast falhou: {e})", file=sys.stderr)

    if not args.no_scan:
        subnet = args.subnet or default_subnet()
        print(f"[*] Varredura TCP {SERVICE_PORT} em {subnet}...", file=sys.stderr)
        for ip in scan_subnet(subnet, args.scan_timeout):
            results.setdefault(ip, {"HostIP": ip, "_via": "tcp-scan"})

    if not results:
        print("Nenhuma câmera encontrada.", file=sys.stderr)
        print("Dicas: confirme que o PC e a câmera estão na mesma VLAN/rede,"
              " e que a porta 34567 não está bloqueada por firewall.",
              file=sys.stderr)
        return 1

    print(f"\n{len(results)} aparelho(s) encontrado(s):\n")
    for ip, info in sorted(results.items()):
        print(f"  IP        : {info.get('HostIP', ip)}")
        if info.get("HostName"):
            print(f"  Nome      : {info['HostName']}")
        if info.get("MAC"):
            print(f"  MAC       : {info['MAC']}")
        if info.get("TCPPort"):
            print(f"  TCP Port  : {info['TCPPort']}")
        if info.get("HttpPort"):
            print(f"  HTTP Port : {info['HttpPort']}")
        if info.get("GateWay"):
            print(f"  Gateway   : {info['GateWay']}")
        if info.get("_via"):
            print(f"  (detectado por varredura TCP; sem resposta ao broadcast)")
        print(f"  -> teste : python3 icsee_client.py --host {info.get('HostIP', ip)} "
              f"--password SENHA info\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
