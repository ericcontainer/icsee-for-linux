#!/usr/bin/env python3
"""
icsee_client.py — Cliente Linux (Python 3) para câmeras/DVRs iCSee / XMeye
(Xiongmai), falando o protocolo LAN DVRIP / "Sofia" na porta TCP 34567.

Reconstruído a partir da análise estática de libFunSDK.so (iCSee 7.9.7_G) com
REA + conhecimento público do protocolo DVRIP. Fala direto com o aparelho na
rede local — NÃO usa a nuvem/P2P da Xiongmai.

Uso rápido:
    python3 icsee_client.py --host 192.168.1.10 --user admin --password "" info
    python3 icsee_client.py --host 192.168.1.10 --password SENHA snapshot foto.jpg
    python3 icsee_client.py --host 192.168.1.10 --password SENHA record 15 video.h264
    python3 icsee_client.py --host 192.168.1.10 --password SENHA ptz right 0.5
    python3 icsee_client.py --host 192.168.1.10 --password SENHA getconfig General

Dependências: apenas a biblioteca padrão do Python 3 (socket, struct, hashlib,
json, threading). Nenhum pacote externo é necessário.
"""

import argparse
import hashlib
import json
import socket
import struct
import sys
import threading
import time

# --- Códigos de mensagem DVRIP (QCODE) ------------------------------------
# Cada comando tem um id numérico no cabeçalho binário e um "Name" no JSON.
QCODES = {
    "LOGIN_REQ2":        1000,
    "LOGIN_RSP":         1001,
    "LOGOUT_REQ":        1001,
    "FORCELOGOUT_REQ":   1002,
    "KEEPALIVE_REQ":     1006,
    "SYSINFO_REQ":       1020,
    "SYSINFO_RSP":       1021,
    "CONFIG_SET":        1040,
    "CONFIG_GET":        1042,
    "DEFAULT_CONFIG_GET":1044,
    "ABILITY_GET":       1360,
    "PTZ_REQ":           1400,
    "MONITOR_REQ":       1410,
    "MONITOR_DATA":      1412,
    "MONITOR_CLAIM":     1413,
    "PLAY_REQ":          1420,
    "PLAY_CLAIM":        1423,
    "TALK_REQ":          1430,
    "TALK_CLAIM":        1434,
    "SNAP_REQ":          1560,   # OPSNAP
    "GUARD_REQ":         1500,
    "ALARM_REQ":         1504,
    "TIMEQUERY_REQ":     1452,
    "FILESEARCH_REQ":    1440,
}

HEAD_FLAG = 0xFF


def sofia_hash(password: str) -> str:
    """Hash de senha do DVRIP ("sofia hash").

    MD5(senha) -> 16 bytes -> 8 pares de bytes -> índice num alfabeto de 62
    caracteres, resultando em 8 caracteres. Senha vazia produz "tlJwpbo6".
    """
    md5 = hashlib.md5(password.encode("utf-8")).digest()
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    out = []
    for i in range(8):
        n = (md5[2 * i] + md5[2 * i + 1]) % 62
        out.append(chars[n])
    return "".join(out)


class DVRIPError(Exception):
    pass


# Mapa de códigos de retorno conhecidos do campo "Ret".
RET_MESSAGES = {
    100: "OK",
    101: "Erro desconhecido",
    102: "Versão não suportada",
    103: "Requisição ilegal",
    104: "Usuário já logado",
    105: "Usuário não logado",
    106: "Usuário ou senha incorretos",
    107: "Sem permissão",
    203: "Senha incorreta",
    204: "Usuário inválido",
    205: "Usuário bloqueado",
    511: "Já iniciado",
    512: "Não iniciado",
}


class DVRIPClient:
    def __init__(self, host, port=34567, timeout=10):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self.session = 0
        self.seq = 0
        self.device_info = {}
        self._keepalive = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # -- conexão -----------------------------------------------------------
    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), self.timeout)
        self.sock.settimeout(self.timeout)

    def close(self):
        self._stop.set()
        if self._keepalive:
            self._keepalive.join(timeout=2)
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *a):
        try:
            self.logout()
        except Exception:
            pass
        self.close()

    # -- protocolo binário -------------------------------------------------
    def _send(self, msgid, payload):
        """Monta e envia um pacote DVRIP. payload = dict ou str."""
        if isinstance(payload, dict):
            data = json.dumps(payload).encode("utf-8")
        elif isinstance(payload, str):
            data = payload.encode("utf-8")
        else:
            data = payload
        # Terminador padrão esperado pelo firmware.
        data = data + b"\x0a\x00"
        with self._lock:
            self.seq = (self.seq + 1) & 0xFFFFFFFF
            # BB2xII2xHI:
            #  B  head_flag=0xFF
            #  B  version=0
            #  2x reservado
            #  I  session
            #  I  sequence
            #  2x total_pkt, cur_pkt
            #  H  msgid
            #  I  tamanho dos dados
            header = struct.pack(
                "<BBxxIIxxHI",
                HEAD_FLAG, 0, self.session, self.seq, msgid, len(data)
            )
            self.sock.sendall(header + data)

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise DVRIPError("conexão fechada pelo dispositivo")
            buf += chunk
        return buf

    def _recv(self):
        """Lê um pacote DVRIP. Retorna (msgid, bytes_do_payload)."""
        header = self._recv_exact(20)
        head_flag, ver, session, seq, msgid, length = struct.unpack(
            "<BBxxIIxxHI", header
        )
        if head_flag != HEAD_FLAG:
            raise DVRIPError(f"cabeçalho inválido: {head_flag:#x}")
        data = self._recv_exact(length) if length else b""
        return msgid, data

    def _recv_json(self):
        msgid, data = self._recv()
        data = data.rstrip(b"\x00").rstrip(b"\n").rstrip(b"\x00")
        try:
            obj = json.loads(data.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            obj = {"_raw": data}
        return msgid, obj

    @staticmethod
    def _check_ret(obj):
        ret = obj.get("Ret")
        if ret is not None and ret not in (100, 515):  # 515 = sucesso p/ alguns
            msg = RET_MESSAGES.get(ret, f"código {ret}")
            raise DVRIPError(f"dispositivo retornou Ret={ret} ({msg})")
        return obj

    # -- comandos de alto nível -------------------------------------------
    def login(self, user="admin", password="", keepalive=True):
        if self.sock is None:
            self.connect()
        self._send(QCODES["LOGIN_REQ2"], {
            "EncryptType": "MD5",
            "LoginType": "DVRIP-Web",
            "PassWord": sofia_hash(password),
            "UserName": user,
        })
        _, obj = self._recv_json()
        self._check_ret(obj)
        sid = obj.get("SessionID", "0x0")
        self.session = int(sid, 16) if isinstance(sid, str) else int(sid)
        self.device_info = obj
        if keepalive:
            self._start_keepalive(obj.get("AliveInterval", 20))
        return obj

    def logout(self):
        if self.sock is None or self.session == 0:
            return
        self._send(QCODES["LOGOUT_REQ"], {"Name": "", "SessionID": self._sid()})
        try:
            self._recv_json()
        except Exception:
            pass

    def _sid(self):
        return "0x%08X" % self.session

    def _start_keepalive(self, interval):
        interval = max(5, int(interval) - 2)

        def loop():
            while not self._stop.wait(interval):
                try:
                    self._send(QCODES["KEEPALIVE_REQ"],
                               {"Name": "KeepAlive", "SessionID": self._sid()})
                    self._recv_json()
                except Exception:
                    break

        self._keepalive = threading.Thread(target=loop, daemon=True)
        self._keepalive.start()

    def system_info(self):
        self._send(QCODES["SYSINFO_REQ"],
                   {"Name": "SystemInfo", "SessionID": self._sid()})
        _, obj = self._recv_json()
        return obj

    def get_config(self, name):
        """Lê um bloco de configuração, ex.: 'General', 'NetWork.NetCommon',
        'Camera.Param', 'Simplify.Encode'."""
        self._send(QCODES["CONFIG_GET"],
                   {"Name": name, "SessionID": self._sid()})
        _, obj = self._recv_json()
        return obj

    def set_config(self, name, value):
        payload = {"Name": name, "SessionID": self._sid(), name: value}
        self._send(QCODES["CONFIG_SET"], payload)
        _, obj = self._recv_json()
        return self._check_ret(obj)

    def get_ability(self, name="SystemFunction"):
        self._send(QCODES["ABILITY_GET"],
                   {"Name": name, "SessionID": self._sid()})
        _, obj = self._recv_json()
        return obj

    # -- PTZ ---------------------------------------------------------------
    def ptz(self, direction, speed=0.4, stop=False, channel=0,
            read_response=True):
        """Controle PTZ. direction: up/down/left/right/
        upleft/upright/downleft/downright/zoomin/zoomout/focusfar/focusnear/
        irisopen/irisclose."""
        cmd_map = {
            "up": "DirectionUp", "down": "DirectionDown",
            "left": "DirectionLeft", "right": "DirectionRight",
            "upleft": "DirectionLeftUp", "upright": "DirectionRightUp",
            "downleft": "DirectionLeftDown", "downright": "DirectionRightDown",
            "zoomin": "ZoomTile", "zoomout": "ZoomWide",
            "focusfar": "FocusFar", "focusnear": "FocusNear",
            "irisopen": "IrisLarge", "irisclose": "IrisSmall",
        }
        if direction not in cmd_map:
            raise ValueError(f"direção PTZ inválida: {direction}")
        sp = max(0, min(8, int(round(speed * 8))))
        payload = {
            "Name": "OPPTZControl",
            "SessionID": self._sid(),
            "OPPTZControl": {
                "Command": cmd_map[direction],
                "Parameter": {
                    "AUX": {"Number": 0, "Status": "On"},
                    "Channel": channel,
                    "MenuOpts": "Enter",
                    "POINT": {"bottom": 0, "left": 0, "right": 0, "top": 0},
                    "Pattern": "Start",
                    "Preset": -1 if not stop else -1,
                    "Step": sp,
                    "Tour": 0,
                },
            },
        }
        self._send(QCODES["PTZ_REQ"], payload)
        # Durante o streaming, o loop de vídeo é quem lê o socket. Ler a
        # resposta aqui, de outro thread, causaria corrida e travaria o vídeo;
        # por isso read_response=False no uso concorrente (o loop descarta a
        # resposta JSON ao demultiplexar).
        if read_response:
            _, obj = self._recv_json()
            return obj
        return None

    def ptz_move(self, direction, duration=0.5, speed=0.4, channel=0,
                 read_response=True):
        """Move no PTZ por `duration` segundos e para."""
        self.ptz(direction, speed=speed, stop=False, channel=channel,
                 read_response=read_response)
        time.sleep(duration)
        # Repetir o mesmo comando encerra o movimento no firmware XM.
        self.ptz(direction, speed=speed, stop=True, channel=channel,
                 read_response=read_response)

    # -- snapshot ----------------------------------------------------------
    def snapshot(self, channel=0):
        """Captura um quadro JPEG via OPSNAP. Retorna bytes JPEG."""
        self._send(QCODES["SNAP_REQ"], {
            "Name": "OPSNAP",
            "SessionID": self._sid(),
            "OPSNAP": {"Channel": channel},
        })
        # A resposta vem como pacote de mídia (msgid 1561/1562). Lemos até
        # encontrar dados binários JPEG.
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            msgid, data = self._recv()
            data = data.lstrip(b"\x00")
            if data[:2] == b"\xff\xd8":  # SOI de JPEG
                # Alguns firmwares anexam \x0a\x00; cortamos após EOI.
                end = data.rfind(b"\xff\xd9")
                return data[: end + 2] if end != -1 else data
            # Pacote JSON de controle; ignora e continua.
        raise DVRIPError("não recebeu JPEG do snapshot")

    # -- stream de vídeo ---------------------------------------------------
    def _monitor_action(self, action, channel, stream):
        self._send(QCODES["MONITOR_REQ"] if action != "Claim"
                   else QCODES["MONITOR_CLAIM"], {
            "Name": "OPMonitor",
            "SessionID": self._sid(),
            "OPMonitor": {
                "Action": action,
                "Parameter": {
                    "Channel": channel,
                    "CombinMode": "NONE",
                    "StreamType": stream,
                    "TransMode": "TCP",
                },
            },
        })

    def stream_to(self, sink, duration=None, channel=0, stream="Main",
                  should_stop=None, audio_sink=None):
        """Abre OPMonitor e escreve o Elementary Stream (H.264/H.265 Annex-B)
        em `sink` (objeto com .write(bytes)) até `duration` segundos, até
        `should_stop()` retornar True, ou até erro/Ctrl-C.

        Retorna o total de bytes de vídeo escritos.
        """
        self._monitor_action("Claim", channel, stream)
        self._recv_json()
        self._monitor_action("Start", channel, stream)

        written = 0
        deadline = time.time() + duration if duration else None
        next_ka = time.time() + 15
        media = bytearray()   # buffer contínuo (um frame cruza vários pacotes)
        try:
            while True:
                if deadline and time.time() >= deadline:
                    break
                if should_stop and should_stop():
                    break
                # Keepalive inline: enviado pelo mesmo thread que lê o socket,
                # evitando condição de corrida com um thread separado. A
                # resposta JSON vira bytes no buffer e é ignorada pelo demux.
                if time.time() >= next_ka:
                    try:
                        self._send(QCODES["KEEPALIVE_REQ"],
                                   {"Name": "KeepAlive", "SessionID": self._sid()})
                    except Exception:
                        pass
                    next_ka = time.time() + 15
                try:
                    _, data = self._recv()
                except socket.timeout:
                    continue
                media += data
                payload = self._demux_media(media, audio_sink=audio_sink)
                if payload:
                    sink.write(payload)
                    try:
                        sink.flush()
                    except Exception:
                        pass
                    written += len(payload)
        finally:
            try:
                self._monitor_action("Stop", channel, stream)
            except Exception:
                pass
        return written

    def record(self, out_path, seconds=10, channel=0, stream="Main"):
        """Grava o fluxo ao vivo por `seconds` num arquivo Annex-B.
        Reproduza com `ffplay arquivo` ou empacote: `ffmpeg -i arq -c copy x.mp4`.
        """
        with open(out_path, "wb") as f:
            return self.stream_to(f, duration=seconds, channel=channel,
                                  stream=stream)

    @staticmethod
    def _find_xm_header(buf, start):
        """Acha o próximo cabeçalho de frame Xiongmai (00 00 01 + tipo 0xF0..0xFF)
        a partir de `start`. Retorna o índice ou -1."""
        n = len(buf)
        i = start
        while i + 4 <= n:
            if buf[i] == 0 and buf[i + 1] == 0 and buf[i + 2] == 1 and buf[i + 3] >= 0xF0:
                return i
            i += 1
        return -1

    def _demux_media(self, buf, audio_sink=None):
        """Demultiplexa o fluxo de mídia DVRIP contínuo, extraindo o vídeo
        (Elementary Stream Annex-B) e, se `audio_sink` for dado, entregando
        o áudio (G.711 A-law 8kHz mono) a ele via audio_sink(bytes).

        Cada frame é precedido por um cabeçalho Xiongmai `00 00 01 <tipo>`:
          0xFC/0xFE = vídeo I  -> header 16B, tamanho do payload em [12:16]
          0xFD      = vídeo P  -> header  8B, tamanho do payload em [4:8]
          0xFA      = áudio    -> header  8B, tamanho do payload em [6:8]
          0xF8/0xF9 = extra    -> header  8B, tamanho do payload em [6:8]
        (offsets confirmados por captura real do firmware V5.00.R02).

        `buf` é um bytearray acumulado entre pacotes; esta função consome os
        frames completos e deixa o restante (frame parcial) no buffer.
        """
        out = bytearray()
        i = 0
        n = len(buf)
        while True:
            if i + 4 > n:
                break
            if (buf[i] == 0 and buf[i + 1] == 0 and buf[i + 2] == 1
                    and buf[i + 3] >= 0xF0):
                t = buf[i + 3]
                if t in (0xFC, 0xFE):          # vídeo I
                    if i + 16 > n:
                        break
                    hdr, plen = 16, struct.unpack_from("<I", buf, i + 12)[0]
                    video = True
                elif t == 0xFD:                # vídeo P
                    if i + 8 > n:
                        break
                    hdr, plen = 8, struct.unpack_from("<I", buf, i + 4)[0]
                    video = True
                elif t in (0xFA, 0xF9, 0xF8):  # áudio / extra
                    if i + 8 > n:
                        break
                    hdr, plen = 8, struct.unpack_from("<H", buf, i + 6)[0]
                    video = False
                else:
                    i += 1
                    continue
                if i + hdr + plen > n:
                    break                      # frame incompleto: aguarda mais
                if video:
                    out += buf[i + hdr:i + hdr + plen]
                elif t == 0xFA and audio_sink is not None:
                    try:
                        audio_sink(bytes(buf[i + hdr:i + hdr + plen]))
                    except Exception:
                        pass
                i += hdr + plen
            else:
                # Desalinhado (início do stream ou ruído): ressincroniza no
                # próximo cabeçalho XM.
                nxt = self._find_xm_header(buf, i + 1)
                if nxt < 0:
                    # nenhum cabeçalho à frente; mantém só a cauda (um cabeçalho
                    # pode estar partido no limite do buffer).
                    i = max(i, n - 3)
                    break
                i = nxt
        del buf[:i]
        return bytes(out)


# --- CLI -------------------------------------------------------------------
def _print_json(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Cliente Linux para câmeras/DVRs iCSee/XMeye (Xiongmai) "
                    "via protocolo LAN DVRIP (porta 34567).")
    p.add_argument("--host", required=True, help="IP da câmera/DVR na LAN")
    p.add_argument("--port", type=int, default=34567)
    p.add_argument("--user", default="admin")
    p.add_argument("--password", default="", help='senha (padrão: vazia)')
    p.add_argument("--timeout", type=float, default=10)

    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="imprime SystemInfo do aparelho")
    sub.add_parser("login", help="testa o login e mostra a resposta")

    g = sub.add_parser("getconfig", help="lê um bloco de configuração")
    g.add_argument("name", help="ex.: General, NetWork.NetCommon, Simplify.Encode")

    a = sub.add_parser("ability", help="lê capacidades do aparelho")
    a.add_argument("name", nargs="?", default="SystemFunction")

    s = sub.add_parser("snapshot", help="captura um JPEG")
    s.add_argument("out", help="arquivo .jpg de saída")
    s.add_argument("--channel", type=int, default=0)

    lv = sub.add_parser("live", help="visualização ao vivo (abre janela ffplay/mpv)")
    lv.add_argument("--channel", type=int, default=0)
    lv.add_argument("--stream", default="Extra1", choices=["Main", "Extra1", "Extra2"],
                    help="Extra1 = substream (menor latência); Main = full-res")
    lv.add_argument("--player", default="auto", choices=["auto", "ffplay", "mpv"])

    r = sub.add_parser("record", help="grava vídeo ao vivo (H.264 Annex-B)")
    r.add_argument("seconds", type=float)
    r.add_argument("out", help="arquivo .h264 de saída")
    r.add_argument("--channel", type=int, default=0)
    r.add_argument("--stream", default="Main", choices=["Main", "Extra1", "Extra2"])

    z = sub.add_parser("ptz", help="controle PTZ")
    z.add_argument("direction")
    z.add_argument("duration", nargs="?", type=float, default=0.5)
    z.add_argument("--speed", type=float, default=0.4)
    z.add_argument("--channel", type=int, default=0)

    args = p.parse_args(argv)

    cli = DVRIPClient(args.host, args.port, args.timeout)
    try:
        cli.connect()
        # Streaming faz keepalive inline; os demais comandos usam o thread.
        obj = cli.login(args.user, args.password, keepalive=False)
        if args.cmd == "login":
            _print_json(obj)
        elif args.cmd == "info":
            _print_json(cli.system_info())
        elif args.cmd == "getconfig":
            _print_json(cli.get_config(args.name))
        elif args.cmd == "ability":
            _print_json(cli.get_ability(args.name))
        elif args.cmd == "snapshot":
            jpg = cli.snapshot(args.channel)
            with open(args.out, "wb") as f:
                f.write(jpg)
            print(f"snapshot salvo: {args.out} ({len(jpg)} bytes)")
        elif args.cmd == "live":
            import shutil
            import subprocess
            player = args.player
            if player == "auto":
                player = ("ffplay" if shutil.which("ffplay")
                          else "mpv" if shutil.which("mpv") else None)
            if player is None:
                print("ERRO: instale ffplay (ffmpeg) ou mpv para a visualização "
                      "ao vivo.", file=sys.stderr)
                return 3
            if player == "ffplay":
                cmd = ["ffplay", "-hide_banner", "-loglevel", "error",
                       "-fflags", "nobuffer", "-flags", "low_delay",
                       "-framedrop", "-infbuf",
                       "-window_title", f"iCSee {args.host} ({args.stream})",
                       "-i", "pipe:0"]
            else:  # mpv
                cmd = ["mpv", "--really-quiet", "--profile=low-latency",
                       "--no-cache", f"--title=iCSee {args.host}", "-"]
            print(f"ao vivo: {args.host} canal {args.channel} ({args.stream}) "
                  f"via {player} — feche a janela ou Ctrl-C para sair",
                  file=sys.stderr)
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            try:
                cli.stream_to(proc.stdin, duration=None,
                              channel=args.channel, stream=args.stream,
                              should_stop=lambda: proc.poll() is not None)
            except KeyboardInterrupt:
                pass
            finally:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
                proc.wait()
        elif args.cmd == "record":
            print(f"gravando {args.seconds}s do canal {args.channel} "
                  f"({args.stream})...")
            n = cli.record(args.out, args.seconds, args.channel, args.stream)
            print(f"vídeo salvo: {args.out} ({n} bytes H.264)")
            print(f"reproduza com:  ffplay {args.out}")
        elif args.cmd == "ptz":
            cli.ptz_move(args.direction, args.duration, args.speed, args.channel)
            print(f"PTZ {args.direction} por {args.duration}s")
    except DVRIPError as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 2
    except (socket.timeout, ConnectionError, OSError) as e:
        print(f"ERRO de rede: {e}", file=sys.stderr)
        return 1
    finally:
        cli.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
