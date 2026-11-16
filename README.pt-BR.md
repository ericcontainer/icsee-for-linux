# 📹 iCSee for Linux — Cliente e visualizador para câmeras/DVRs Xiongmai (iCSee / XMEye)

> 🇧🇷 Versão em português. English: [README.md](README.md). Se este projeto te ajudou, deixe uma ⭐ no GitHub!


Cliente **Python puro** para câmeras IP e DVRs baseados em chipset **Xiongmai**
(as vendidas sob os apps **iCSee** e **XMEye**, entre outros). Fala o protocolo
nativo **DVRIP / "Sofia"** direto com o aparelho na rede local (porta TCP
`34567`), sem depender de nuvem, app proprietário ou plugins de navegador.

Inclui:

- 🔎 **Descoberta** de câmeras na rede local (`discover.py`)
- 🖥️ **Cliente de linha de comando** (`icsee_client.py`): info, snapshot, gravação, vídeo ao vivo, PTZ, leitura de configurações
- 🪟 **Interface gráfica** (`icsee_gui.py`): vídeo ao vivo, áudio, PTZ, foto e gravação, com janela redimensionável

> Projetado e testado em **Linux**. O núcleo do protocolo é multiplataforma;
> a GUI e o áudio usam ferramentas comuns de Linux (ffmpeg, aplay/pw-play).

---

## Índice

- [Recursos](#recursos)
- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Uso rápido](#uso-rápido)
- [Descoberta de câmeras](#descoberta-de-câmeras)
- [Cliente de linha de comando](#cliente-de-linha-de-comando)
- [Interface gráfica](#interface-gráfica)
- [Como funciona (protocolo)](#como-funciona-protocolo)
- [Acesso pela internet](#acesso-pela-internet)
- [Solução de problemas](#solução-de-problemas)
- [Segurança](#segurança)
- [Aviso legal](#aviso-legal)
- [Licença](#licença)

---

## Recursos

| Recurso | CLI | GUI |
|---|:---:|:---:|
| Login DVRIP (hash de senha "sofia") | ✅ | ✅ |
| Informações do sistema (`SystemInfo`) | ✅ | — |
| Leitura de configurações (`getconfig`) | ✅ | — |
| Capacidades do aparelho (`ability`) | ✅ | — |
| Snapshot JPEG | ✅ | ✅ |
| Vídeo ao vivo (H.264 **e** H.265/HEVC) | ✅ | ✅ |
| Gravação em arquivo (Elementary Stream) | ✅ | ✅ |
| Áudio ao vivo (G.711 A-law) | — | ✅ |
| Controle PTZ / zoom | ✅ | ✅ |
| Janela redimensionável (mantém proporção) | — | ✅ |
| Keepalive automático da sessão | ✅ | ✅ |

---

## Requisitos

**Núcleo do protocolo (`icsee_client.py`, `discover.py`):**
- Python **3.8+** (somente biblioteca padrão — zero dependências externas)

**Interface gráfica e mídia (`icsee_gui.py`):**
- Python **3.8 – 3.12** (o áudio usa o módulo `audioop`, removido no 3.13)
- [`ffmpeg`](https://ffmpeg.org/) no `PATH` (decodifica o vídeo H.264/H.265)
- Python: `Pillow` e `numpy`
- Para áudio: `aplay` (pacote `alsa-utils`) **ou** `pw-play` (PipeWire). Opcional.

Instale as dependências Python:

```bash
pip install -r requirements.txt
```

E o ffmpeg (exemplos):

```bash
# Debian/Ubuntu
sudo apt install ffmpeg alsa-utils
# Fedora
sudo dnf install ffmpeg alsa-utils
# Arch
sudo pacman -S ffmpeg alsa-utils
```

---

## Instalação

```bash
git clone https://github.com/admin/icsee-for-linux.git
cd icsee-for-linux
pip install -r requirements.txt
```

Não há etapa de build — são scripts Python.

---

## Uso rápido

```bash
# 1) Encontrar a câmera na rede
python3 discover.py

# 2) Testar o login e ver informações
python3 icsee_client.py --host 192.168.1.10 --user admin --password SENHA info

# 3) Abrir a interface gráfica
python3 icsee_gui.py --host 192.168.1.10 --user admin --password SENHA
```

> O usuário padrão de fábrica costuma ser `admin`. A senha de fábrica
> frequentemente é **vazia** (`--password ""`).

---

## Descoberta de câmeras

`discover.py` combina dois métodos: um **broadcast UDP** do protocolo de busca
(porta `34569`) e uma **varredura TCP** da porta `34567` na sub-rede local.

```bash
# Automático (detecta a sub-rede da interface padrão)
python3 discover.py

# Especificar a sub-rede
python3 discover.py --subnet 192.168.1.0/24

# Só broadcast (mais rápido) ou só varredura
python3 discover.py --no-scan
python3 discover.py --no-broadcast
```

Saída típica:

```
3 aparelho(s) encontrado(s):

  IP        : 192.168.1.10
  Nome      : camera_2e30
  MAC       : f8:16:0c:xx:xx:xx
  TCP Port  : 34567
  HTTP Port : 80
  Gateway   : 192.168.1.1
  -> teste : python3 icsee_client.py --host 192.168.1.10 --password SENHA info
```

---

## Cliente de linha de comando

```
python3 icsee_client.py --host HOST [--user USER] [--password SENHA] COMANDO
```

Opções globais: `--host` (obrigatório), `--port` (padrão `34567`),
`--user` (padrão `admin`), `--password` (padrão vazio), `--timeout`.

### Comandos

| Comando | Descrição |
|---|---|
| `info` | Mostra o `SystemInfo` (modelo, firmware, canais, etc.) |
| `login` | Testa a autenticação e mostra a resposta |
| `getconfig <nome>` | Lê um bloco de configuração |
| `ability [nome]` | Lê capacidades do aparelho (padrão `SystemFunction`) |
| `snapshot <arq.jpg>` | Captura um quadro JPEG |
| `record <seg> <arq>` | Grava vídeo ao vivo por N segundos |
| `live` | Visualização ao vivo em janela (requer `ffplay` ou `mpv`) |
| `ptz <direção> [dur]` | Controle PTZ / zoom |

### Exemplos

```bash
# Informações do aparelho
python3 icsee_client.py --host 192.168.1.10 --password SENHA info

# Foto
python3 icsee_client.py --host 192.168.1.10 --password SENHA snapshot foto.jpg

# Gravar 30s do stream principal
python3 icsee_client.py --host 192.168.1.10 --password SENHA record 30 video.h265
# Empacotar em MP4 sem recodificar:
ffmpeg -framerate 12 -i video.h265 -c copy video.mp4

# Ler configuração de codificação (resolução/bitrate)
python3 icsee_client.py --host 192.168.1.10 --password SENHA getconfig Simplify.Encode

# Ler a configuração de rede
python3 icsee_client.py --host 192.168.1.10 --password SENHA getconfig NetWork.NetCommon

# PTZ: girar para a direita por 0.5s; zoom
python3 icsee_client.py --host 192.168.1.10 --password SENHA ptz right 0.5
python3 icsee_client.py --host 192.168.1.10 --password SENHA ptz zoomin
```

Direções de PTZ: `up`, `down`, `left`, `right`, `upleft`, `upright`,
`downleft`, `downright`, `zoomin`, `zoomout`, `focusfar`, `focusnear`,
`irisopen`, `irisclose`.

Blocos de configuração úteis para `getconfig`: `General`, `NetWork.NetCommon`,
`NetWork.Ddns`, `Simplify.Encode`, `Camera.Param`, `fVideo.Volume`,
`AVEnc.VideoWidget`.

### Uso como biblioteca

```python
from icsee_client import DVRIPClient

with DVRIPClient("192.168.1.10") as cam:
    cam.login("admin", "SENHA")
    print(cam.system_info())
    jpg = cam.snapshot()
    open("foto.jpg", "wb").write(jpg)
    cam.record("video.h265", seconds=10)
```

---

## Interface gráfica

```bash
python3 icsee_gui.py --host 192.168.1.10 --user admin --password SENHA
```

Os campos de conexão também podem ser preenchidos na própria janela, deixando
os argumentos de fora:

```bash
python3 icsee_gui.py
```

Na janela:

- **Vídeo ao vivo** no centro — a janela é redimensionável e o vídeo acompanha,
  mantendo a proporção.
- Seletor **Stream**: `Main` (alta resolução) ou `Extra1` (substream, mais leve).
- Seletor **Codec**: `hevc` (H.265) ou `h264` — ajuste conforme a câmera.
- **Setas de PTZ** e **Zoom +/−** à esquerda.
- **📷 Foto**: salva o quadro atual em JPEG.
- **🔊 Áudio**: liga/desliga o áudio ao vivo (começa desligado).
- **⏺ Gravar**: grava o vídeo em arquivo (inicia/para).

---

## Como funciona (protocolo)

Os aparelhos Xiongmai expõem na LAN o protocolo **DVRIP** (também chamado de
"Sofia") na porta TCP **34567**. Cada mensagem tem um cabeçalho binário de 20
bytes seguido de um corpo em **JSON**.

**Cabeçalho (20 bytes, little-endian):**

| Offset | Tamanho | Campo |
|---|---|---|
| 0 | 1 | `0xFF` (flag) |
| 1 | 1 | versão (`0x00`) |
| 2 | 2 | reservado |
| 4 | 4 | SessionID |
| 8 | 4 | número de sequência |
| 12 | 2 | total/atual de pacotes |
| 14 | 2 | ID da mensagem |
| 16 | 4 | tamanho dos dados |

**Login:** a senha é transformada por um hash próprio ("sofia hash") — MD5 da
senha, reduzido a 8 caracteres de um alfabeto de 62. (Senha vazia →
`tlJwpbo6`.) O corpo do login é:

```json
{"EncryptType":"MD5","LoginType":"DVRIP-Web","PassWord":"<hash>","UserName":"admin"}
```

**Vídeo:** o comando `OPMonitor` abre o fluxo de mídia. Cada quadro vem
precedido de um pequeno cabeçalho Xiongmai (`00 00 01 <tipo>`), onde o tipo
indica I-frame de vídeo, P-frame, áudio, etc. O cliente demultiplexa esse fluxo,
remonta quadros que cruzam vários pacotes de rede e entrega o
**Elementary Stream** H.264/H.265 (Annex-B) pronto para decodificar.

**Áudio:** fluxo **G.711 A-law, 8 kHz, mono**, embutido no mesmo stream de mídia.

---

## Acesso pela internet

Este projeto fala com o aparelho na **rede local**. Para acessá-lo de fora, as
opções recomendadas (mais seguras e confiáveis) são:

- **VPN** (ex.: [WireGuard](https://www.wireguard.com/) ou
  [Tailscale](https://tailscale.com/)): instale num dispositivo que fique ligado
  na mesma rede da câmera; de fora, conecte pela VPN e use o IP local da câmera
  normalmente. **Não expõe a câmera à internet.**
- **Redirecionamento de porta + DDNS** no roteador: encaminhe a porta `34567`
  para a câmera. Funciona imediatamente, mas **expõe o aparelho** — use senha
  forte e, de preferência, uma porta externa não padrão.

> O recurso de acesso "mágico" sem configuração dos apps oficiais usa a **nuvem
> P2P proprietária** do fabricante, que **não** é implementada aqui.

---

## Solução de problemas

**`Ret=205` / "usuário bloqueado" no login**
O firmware tem proteção anti-força-bruta: várias tentativas de senha erradas
bloqueiam a conta (e às vezes fecham a porta) por alguns minutos. Espere ~1–5
min ou reinicie o aparelho, depois use a senha correta.

**`Connection refused` na porta 34567**
A proteção acima pode ter fechado o serviço temporariamente; aguarde o
cooldown. Confirme também que o PC e a câmera estão na mesma rede/VLAN.

**A GUI conecta mas o vídeo não aparece**
Verifique se o **codec** está correto (`hevc` × `h264`). Cameras 4MP/8MP
costumam usar **H.265 (hevc)**.

**Imagem com a parte de cima boa e o resto corrompido**
Normalmente indica codec errado ou perda de pacotes; alterne o stream para
`Extra1` para testar.

**Vídeo picotado / travando**
O PC pode não dar conta do stream `Main` em alta resolução. Use o stream
`Extra1` na GUI.

**Áudio sem som**
Instale `alsa-utils` (`aplay`) ou PipeWire (`pw-play`). O áudio do ambiente
também pode estar simplesmente muito baixo — fale perto da câmera para testar.

---

## Segurança

- **Troque a senha padrão** do aparelho.
- Prefira acesso remoto por **VPN** a expor a porta na internet.
- As credenciais passadas por `--password` podem ficar visíveis no histórico do
  shell e na lista de processos. Para uso sensível, prefira a GUI (campo de
  senha) ou adapte o código para ler a senha de uma variável de ambiente.

---

## Aviso legal

Projeto independente, **sem qualquer vínculo** com a Xiongmai ou com os apps
iCSee/XMEye. Nomes de produtos e marcas pertencem aos seus respectivos donos.
Use **apenas em equipamentos que você possui ou está autorizado a administrar**.
O protocolo foi implementado de forma independente para interoperabilidade na
rede local. Fornecido "como está", sem garantias.

---

## Licença

[MIT](LICENSE)
