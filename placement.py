"""Procura, perto do rodapé de uma página, uma área livre para o carimbo da assinatura.

A página é renderizada e só se escolhe um retângulo sem nenhum "tinta" (texto,
imagem, linha, assinatura anterior). Se não houver, devolve None e o chamador
assina sem aparência visual, em vez de cobrir o texto.
"""
from __future__ import annotations

from pathlib import Path

INK_THRESHOLD = 240  # tons de cinza abaixo disso contam como conteúdo
_INK_TABLE = bytes(1 if value < INK_THRESHOLD else 0 for value in range(256))


def find_free_box(
    pdf_path: str | Path,
    width: float,
    height: float,
    page_index: int = -1,
    *,
    margin: float = 14,
    pad: float = 4,
    search_fraction: float = 0.25,
) -> tuple[float, float, float, float] | None:
    """Retorna (x1, y1, x2, y2) em pontos PDF (origem embaixo à esquerda), ou None.

    ``margin`` é a distância mínima até a borda da página e ``pad`` a folga em
    volta do carimbo. Só o quarto inferior da página é considerado (rodapé).
    Páginas giradas não são tratadas (devolve None).
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        # sem o ambiente de formulários o pdfium não desenha campos de assinatura,
        # e carimbos de assinaturas anteriores não seriam vistos como conteúdo
        pdf.init_forms()
        page = pdf[page_index if page_index >= 0 else len(pdf) + page_index]
        if page.get_rotation() % 360:
            return None
        left, bottom, right, top = page.get_cropbox()
        bitmap = page.render(scale=1, grayscale=True)
        px_w, px_h, stride = bitmap.width, bitmap.height, bitmap.stride
        if bitmap.n_channels != 1:
            return None
        raw = bytes(bitmap.buffer)
    finally:
        pdf.close()

    rows = [
        raw[i * stride : i * stride + px_w].translate(_INK_TABLE) for i in range(px_h)
    ]

    # margens do texto da página: o carimbo se alinha a elas
    first = [r.find(1) for r in rows]
    first = [x for x in first if x >= 0]
    last = [r.rfind(1) for r in rows]
    last = [x for x in last if x >= 0]
    text_left = min(first) if first else margin
    text_right = max(last) + 1 if last else px_w - margin

    box_w, box_h = int(round(width)), int(round(height))
    pad_i = int(round(pad))
    edge = int(round(margin))
    max_x1 = px_w - edge - box_w
    if max_x1 < edge:
        return None  # página estreita demais para o carimbo

    candidates = [
        int(min(max(text_left, edge), max_x1)),  # alinhado à margem esquerda do texto
        int(min(max(text_right - box_w, edge), max_x1)),  # à direita do texto
        int((px_w - box_w) / 2),  # centralizado
    ]

    lowest = int(px_h * (1 - search_fraction))
    best: tuple[int, int] | None = None  # (linha do topo, x1)
    for x1 in dict.fromkeys(candidates):
        lo, hi = max(x1 - pad_i, 0), min(x1 + box_w + pad_i, px_w)
        row_top = px_h - edge - box_h
        while row_top >= lowest:
            band = range(max(row_top - pad_i, 0), min(row_top + box_h + pad_i, px_h))
            if all(1 not in rows[r][lo:hi] for r in band):
                if best is None or row_top > best[0]:
                    best = (row_top, x1)
                break
            row_top -= 2
    if best is None:
        return None

    row_top, x1 = best
    y_top = top - row_top
    return (left + x1, y_top - box_h, left + x1 + box_w, y_top)
