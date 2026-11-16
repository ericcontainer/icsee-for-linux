#!/usr/bin/env python3
"""
icsee_gui.py — Interface gráfica (Tkinter) para câmeras iCSee/XMeye (Xiongmai).

Mostra o vídeo ao vivo embutido na janela, com controles de PTZ, captura de
foto e gravação. O vídeo H.265/H.264 da câmera é decodificado por ffmpeg e
exibido quadro a quadro via Pillow.

Requisitos: python3-tk (Tkinter), Pillow, numpy, ffmpeg no PATH.
    pip install pillow numpy      # ffmpeg via gerenciador do sistema/conda

Uso:
    python3 icsee_gui.py
    python3 icsee_gui.py --host 192.168.1.10 --user ecwj --password a57aea

Os campos de conexão também podem ser preenchidos na própria janela.
"""

import argparse
import os
import queue
import shutil
import struct
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageTk

from icsee_client import DVRIPClient, DVRIPError

# Resolução de exibição (o ffmpeg reescala a fonte para este tamanho).
# 1280x720 com o fluxo Main (2304x1296) dá imagem nítida. Reduza para
# 960x540 se o PC for fraco e o vídeo travar.
VIEW_W, VIEW_H = 1280, 720


class TeeSink:
    """Escreve os bytes de vídeo no ffmpeg e, opcionalmente, num arquivo."""
    def __init__(self, primary):
        self.primary = primary
        self.record_file = None
        self._lock = threading.Lock()

    def write(self, data):
        try:
            self.primary.write(data)
        except (BrokenPipeError, ValueError, OSError):
            raise
        with self._lock:
            if self.record_file:
                try:
                    self.record_file.write(data)
                except Exception:
                    pass

    def flush(self):
        try:
            self.primary.flush()
        except Exception:
            pass

    def start_record(self, path):
        with self._lock:
            self.record_file = open(path, "wb")

    def stop_record(self):
        with self._lock:
            f, self.record_file = self.record_file, None
        if f:
            f.close()


class CameraSession:
    """Gerencia conexão DVRIP + pipeline ffmpeg + threads de leitura."""
    def __init__(self, host, port, user, password, stream, on_frame, on_status,
                 codec="hevc"):
        self.host, self.port = host, port
        self.user, self.password = user, password
        self.stream = stream
        self.codec = codec            # "hevc" (padrão desta câmera) ou "h264"
        self.on_frame = on_frame      # callback(PIL.Image)
        self.on_status = on_status    # callback(str)
        self.client = None
        self.ffmpeg = None
        self.sink = None
        self.audio_proc = None        # player de áudio (aplay/pw-play)
        self.audio_on = threading.Event()
        self._audio_lock = threading.Lock()
        self._stop = threading.Event()
        self._threads = []

    def start(self):
        self._stop.clear()
        t = threading.Thread(target=self._run, daemon=True)
        t.start()
        self._threads.append(t)

    def _run(self):
        try:
            self.on_status(f"conectando a {self.host}:{self.port}...")
            self.client = DVRIPClient(self.host, self.port, timeout=12)
            self.client.connect()
            self.client.login(self.user, self.password, keepalive=False)
            self.on_status("conectado — iniciando vídeo")
        except (DVRIPError, OSError) as e:
            self.on_status(f"ERRO de login: {e}")
            return

        # ffmpeg: decodifica o Annex-B da câmera -> rawvideo rgb24 reescalado.
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-fflags", "nobuffer", "-flags", "low_delay",
            # Dizer que a entrada é vídeo cru (Annex-B) e cortar a análise
            # evita ~5s de espera até o primeiro quadro. Esta câmera usa HEVC;
            # para câmeras H.264 troque self.codec para "h264".
            "-probesize", "100000", "-analyzeduration", "0",
            "-f", self.codec,
            "-i", "pipe:0",
            "-vf", f"scale={VIEW_W}:{VIEW_H}:force_original_aspect_ratio=decrease:"
                   f"flags=lanczos,"
                   f"pad={VIEW_W}:{VIEW_H}:(ow-iw)/2:(oh-ih)/2",
            "-pix_fmt", "rgb24", "-f", "rawvideo", "-an", "pipe:1",
        ]
        self.ffmpeg = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, bufsize=0)
        self.sink = TeeSink(self.ffmpeg.stdin)

        # Thread 1: lê frames decodificados do ffmpeg e os entrega à GUI.
        tr = threading.Thread(target=self._read_frames, daemon=True)
        tr.start()
        self._threads.append(tr)

        # Thread atual: puxa o stream da câmera para o ffmpeg (+ áudio).
        try:
            self.client.stream_to(
                self.sink, duration=None, channel=0, stream=self.stream,
                should_stop=lambda: self._stop.is_set()
                or self.ffmpeg.poll() is not None,
                audio_sink=self._audio_write)
        except (DVRIPError, OSError, BrokenPipeError) as e:
            if not self._stop.is_set():
                self.on_status(f"stream encerrado: {e}")
        finally:
            self._cleanup()

    def _read_frames(self):
        frame_bytes = VIEW_W * VIEW_H * 3
        out = self.ffmpeg.stdout
        while not self._stop.is_set():
            buf = b""
            while len(buf) < frame_bytes:
                chunk = out.read(frame_bytes - len(buf))
                if not chunk:
                    return
                buf += chunk
            try:
                img = Image.frombytes("RGB", (VIEW_W, VIEW_H), buf)
            except Exception:
                continue
            self.on_frame(img)

    def ptz(self, direction, duration=0.4):
        if not self.client:
            return
        def go():
            try:
                # read_response=False: o loop de vídeo é quem lê o socket.
                self.client.ptz_move(direction, duration=duration, speed=0.5,
                                     read_response=False)
            except Exception as e:
                self.on_status(f"PTZ falhou: {e}")
        threading.Thread(target=go, daemon=True).start()

    # -- áudio ao vivo (G.711 A-law 8kHz mono) -----------------------------
    @staticmethod
    def _audio_player_cmd():
        """Comando do player de áudio disponível. O áudio da câmera é
        G.711 A-law, mas muitas placas não aceitam A-law direto; por isso
        convertemos para PCM S16LE em Python e enviamos S16 ao player."""
        if shutil.which("aplay"):
            return ["aplay", "-q", "-t", "raw", "-f", "S16_LE",
                    "-r", "8000", "-c", "1", "-"]
        if shutil.which("pw-play"):
            return ["pw-play", "--format=s16", "--rate=8000",
                    "--channels=1", "-"]
        if shutil.which("ffplay"):
            return ["ffplay", "-hide_banner", "-loglevel", "quiet",
                    "-nodisp", "-autoexit", "-f", "s16le", "-ar", "8000",
                    "-ac", "1", "-i", "pipe:0"]
        return None

    def set_audio(self, enabled):
        with self._audio_lock:
            if enabled and self.audio_proc is None:
                cmd = self._audio_player_cmd()
                if cmd is None:
                    self.on_status("sem player de áudio (instale alsa-utils/aplay)")
                    return False
                try:
                    self.audio_proc = subprocess.Popen(
                        cmd, stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self.audio_on.set()
                    self.on_status(f"áudio ligado ({cmd[0]})")
                    return True
                except Exception as e:
                    self.on_status(f"falha no áudio: {e}")
                    self.audio_proc = None
                    return False
            elif not enabled and self.audio_proc is not None:
                self.audio_on.clear()
                try:
                    self.audio_proc.stdin.close()
                    self.audio_proc.terminate()
                except Exception:
                    pass
                self.audio_proc = None
                self.on_status("áudio desligado")
        return enabled

    def _audio_write(self, alaw):
        if not self.audio_on.is_set():
            return
        with self._audio_lock:
            p = self.audio_proc
            if p is None or p.stdin is None:
                return
            try:
                import audioop
                p.stdin.write(audioop.alaw2lin(alaw, 2))  # A-law -> PCM S16LE
                p.stdin.flush()
            except Exception:
                pass

    def start_record(self, path):
        if self.sink:
            self.sink.start_record(path)
            self.on_status(f"gravando em {os.path.basename(path)}")

    def stop_record(self):
        if self.sink:
            self.sink.stop_record()
            self.on_status("gravação parada")

    def stop(self):
        self._stop.set()
        self._cleanup()

    def _cleanup(self):
        try:
            self.set_audio(False)
        except Exception:
            pass
        if self.sink:
            try:
                self.sink.stop_record()
            except Exception:
                pass
        if self.ffmpeg:
            for pipe in (self.ffmpeg.stdin, self.ffmpeg.stdout):
                try:
                    pipe.close()
                except Exception:
                    pass
            try:
                self.ffmpeg.terminate()
            except Exception:
                pass
            self.ffmpeg = None
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass


class App(tk.Tk):
    def __init__(self, defaults):
        super().__init__()
        self.title("iCSee — Visualizador")
        self.configure(bg="#1e1e1e")
        self.session = None
        self.latest = None            # último PIL.Image recebido (tamanho-base)
        self.photo = None
        self.recording = False
        self._last_size = (0, 0)      # tamanho já renderizado no canvas
        self._img_item = None         # id do item de imagem no Canvas
        self._frame_q = queue.Queue(maxsize=1)

        self.minsize(480, 360)        # permite encolher bastante
        self._build_ui(defaults)
        self.after(33, self._render_loop)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self, d):
        top = tk.Frame(self, bg="#2a2a2a")
        top.pack(fill="x", padx=6, pady=6)
        self.vars = {}
        for label, key, default, width, show in (
            ("Host", "host", d.get("host", ""), 14, None),
            ("Porta", "port", str(d.get("port", 34567)), 6, None),
            ("Usuário", "user", d.get("user", "admin"), 10, None),
            ("Senha", "password", d.get("password", ""), 12, "*"),
        ):
            tk.Label(top, text=label, bg="#2a2a2a", fg="#ddd").pack(side="left", padx=(6, 2))
            v = tk.StringVar(value=default)
            tk.Entry(top, textvariable=v, width=width, show=show).pack(side="left")
            self.vars[key] = v
        tk.Label(top, text="Stream", bg="#2a2a2a", fg="#ddd").pack(side="left", padx=(6, 2))
        self.stream_var = tk.StringVar(value="Main")
        ttk.Combobox(top, textvariable=self.stream_var, width=7, state="readonly",
                     values=["Main", "Extra1"]).pack(side="left")
        tk.Label(top, text="Codec", bg="#2a2a2a", fg="#ddd").pack(side="left", padx=(6, 2))
        self.codec_var = tk.StringVar(value="hevc")
        ttk.Combobox(top, textvariable=self.codec_var, width=6, state="readonly",
                     values=["hevc", "h264"]).pack(side="left")

        self.connect_btn = tk.Button(top, text="Conectar", command=self._toggle_connect,
                                     bg="#2d7d46", fg="white", width=10)
        self.connect_btn.pack(side="left", padx=8)

        # Vídeo
        # Área de vídeo: um Canvas (não propaga o tamanho da imagem para a
        # janela, evitando o laço de "janela crescendo sozinha").
        self.canvas = tk.Canvas(self, bg="black", highlightthickness=0,
                                width=VIEW_W, height=VIEW_H)
        self.canvas.pack(side="top", padx=6, pady=4, fill="both", expand=True)

        # Controles
        ctl = tk.Frame(self, bg="#1e1e1e")
        ctl.pack(side="bottom", fill="x", padx=6, pady=6)

        # PTZ pad
        pad = tk.Frame(ctl, bg="#1e1e1e")
        pad.pack(side="left")
        grid = [
            ("↖", "upleft", 0, 0), ("↑", "up", 0, 1), ("↗", "upright", 0, 2),
            ("←", "left", 1, 0), ("⟳", None, 1, 1), ("→", "right", 1, 2),
            ("↙", "downleft", 2, 0), ("↓", "down", 2, 1), ("↘", "downright", 2, 2),
        ]
        for text, d_, r, c in grid:
            b = tk.Button(pad, text=text, width=3, height=1,
                          command=(lambda dd=d_: self._ptz(dd)) if d_ else None,
                          state=("disabled" if d_ is None else "normal"))
            b.grid(row=r, column=c, padx=1, pady=1)

        zoom = tk.Frame(ctl, bg="#1e1e1e")
        zoom.pack(side="left", padx=12)
        tk.Button(zoom, text="Zoom +", width=7, command=lambda: self._ptz("zoomin")).pack(pady=1)
        tk.Button(zoom, text="Zoom −", width=7, command=lambda: self._ptz("zoomout")).pack(pady=1)

        actions = tk.Frame(ctl, bg="#1e1e1e")
        actions.pack(side="right")
        tk.Button(actions, text="📷 Foto", width=10, command=self._snapshot).pack(pady=2)
        self.audio_btn = tk.Button(actions, text="🔊 Áudio: OFF", width=10,
                                   command=self._toggle_audio)
        self.audio_btn.pack(pady=2)
        self.rec_btn = tk.Button(actions, text="⏺ Gravar", width=10, command=self._toggle_record)
        self.rec_btn.pack(pady=2)

        self.status = tk.Label(self, text="pronto", bg="#111", fg="#8f8", anchor="w")
        self.status.pack(side="bottom", fill="x")

        # Mensagem inicial (depois que a barra de status já existe).
        self._show_message("Preencha a conexão e clique em Conectar")

    # -- vídeo -------------------------------------------------------------
    def _on_frame(self, img):
        # mantém só o frame mais recente (descarta atrasados = baixa latência)
        try:
            if self._frame_q.full():
                self._frame_q.get_nowait()
            self._frame_q.put_nowait(img)
        except queue.Empty:
            pass
        except queue.Full:
            pass

    def _render_loop(self):
        new = False
        try:
            self.latest = self._frame_q.get_nowait()
            new = True
        except queue.Empty:
            pass
        if self.latest is not None:
            cw = max(self.canvas.winfo_width(), 1)
            ch = max(self.canvas.winfo_height(), 1)
            # Re-renderiza quando há quadro novo OU a janela mudou de tamanho.
            if cw > 1 and ch > 1 and (new or (cw, ch) != self._last_size):
                iw, ih = self.latest.size
                scale = min(cw / iw, ch / ih)        # cabe mantendo proporção
                nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
                disp = (self.latest if (nw, nh) == (iw, ih)
                        else self.latest.resize((nw, nh), Image.BILINEAR))
                self.photo = ImageTk.PhotoImage(disp)
                if self._img_item is None:
                    self._img_item = self.canvas.create_image(
                        cw // 2, ch // 2, image=self.photo, anchor="center")
                else:
                    self.canvas.itemconfig(self._img_item, image=self.photo)
                    self.canvas.coords(self._img_item, cw // 2, ch // 2)
                self._last_size = (cw, ch)
        self.after(33, self._render_loop)

    def _show_message(self, text):
        self.latest = None
        self._last_size = (0, 0)
        if self._img_item is not None:
            self.canvas.delete(self._img_item)
            self._img_item = None
        self._set_status(text)

    def _set_status(self, text):
        self.status.configure(text=text)

    def _status_async(self, text):
        self.after(0, lambda: self._set_status(text))

    # -- ações -------------------------------------------------------------
    def _toggle_connect(self):
        if self.session:
            self.session.stop()
            self.session = None
            self.connect_btn.configure(text="Conectar", bg="#2d7d46")
            self.audio_enabled = False
            self.audio_btn.configure(text="🔊 Áudio: OFF", fg="black")
            self._show_message("desconectado")
            return
        try:
            port = int(self.vars["port"].get())
        except ValueError:
            messagebox.showerror("Erro", "Porta inválida")
            return
        self.session = CameraSession(
            self.vars["host"].get().strip(), port,
            self.vars["user"].get().strip(), self.vars["password"].get(),
            self.stream_var.get(), on_frame=self._on_frame,
            on_status=self._status_async, codec=self.codec_var.get())
        self.session.start()
        self.connect_btn.configure(text="Desconectar", bg="#a23")

    def _ptz(self, direction):
        if self.session:
            self.session.ptz(direction)
            self._set_status(f"PTZ {direction}")

    def _toggle_audio(self):
        if not self.session:
            return
        self.audio_enabled = not getattr(self, "audio_enabled", False)
        ok = self.session.set_audio(self.audio_enabled)
        self.audio_enabled = bool(ok) if self.audio_enabled else False
        self.audio_btn.configure(
            text=f"🔊 Áudio: {'ON' if self.audio_enabled else 'OFF'}",
            fg=("#0a0" if self.audio_enabled else "black"))

    def _snapshot(self):
        if self.latest is None:
            messagebox.showinfo("Foto", "Sem vídeo para capturar ainda.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".jpg", initialfile=time.strftime("foto_%Y%m%d_%H%M%S.jpg"),
            filetypes=[("JPEG", "*.jpg")])
        if path:
            self.latest.save(path, "JPEG", quality=92)
            self._set_status(f"foto salva: {os.path.basename(path)}")

    def _toggle_record(self):
        if not self.session:
            return
        if self.recording:
            self.session.stop_record()
            self.recording = False
            self.rec_btn.configure(text="⏺ Gravar", fg="black")
        else:
            path = filedialog.asksaveasfilename(
                defaultextension=".h265",
                initialfile=time.strftime("video_%Y%m%d_%H%M%S.h265"),
                filetypes=[("HEVC/H.265", "*.h265"), ("H.264", "*.h264")])
            if path:
                self.session.start_record(path)
                self.recording = True
                self.rec_btn.configure(text="⏹ Parar", fg="red")

    def _on_close(self):
        if self.session:
            self.session.stop()
        self.destroy()


def main():
    p = argparse.ArgumentParser(description="GUI para câmeras iCSee/XMeye")
    p.add_argument("--host", default="")
    p.add_argument("--port", type=int, default=34567)
    p.add_argument("--user", default="admin")
    p.add_argument("--password", default="")
    args = p.parse_args()

    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg não encontrado no PATH — instale o ffmpeg.")

    App(vars(args)).mainloop()


if __name__ == "__main__":
    main()
