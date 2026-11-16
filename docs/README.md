# Mídia da documentação

Coloque aqui a captura de tela ou GIF de demonstração:

- `docs/demo.gif` — um GIF curto (5–10s) mostrando o vídeo ao vivo + PTZ/zoom.
- `docs/screenshot.png` — uma captura da janela da GUI conectada.

Depois, descomente a linha correspondente no `README.md` (seção abaixo do título)
para exibir a imagem. Um bom GIF de demonstração é o que mais atrai estrelas. 🌟

Dica para gerar um GIF a partir de uma gravação:
    ffmpeg -i demo.mp4 -vf "fps=12,scale=720:-1:flags=lanczos" -loop 0 docs/demo.gif
