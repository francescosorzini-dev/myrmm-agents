package main

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"image"
	"image/color"
	"image/draw"
	_ "image/gif"
	_ "image/jpeg"
	"image/png"
	"strings"
)

// Funzioni sulle immagini senza nulla di Windows (si provano ovunque): decodifica della bitmap degli appunti,
// riduzione, anteprime per la chat.

// dibToImage legge una bitmap degli appunti (CF_DIB: BITMAPINFOHEADER + pixel). Gestisce 24 e 32 bit, anche dall'alto in basso.
func dibToImage(b []byte) (*image.RGBA, error) {
	if len(b) < 40 {
		return nil, errors.New("bitmap troppo corta")
	}
	hs := int(binary.LittleEndian.Uint32(b[0:]))
	w := int(int32(binary.LittleEndian.Uint32(b[4:])))
	h := int(int32(binary.LittleEndian.Uint32(b[8:])))
	bits := int(binary.LittleEndian.Uint16(b[14:]))
	comp := binary.LittleEndian.Uint32(b[16:])
	clr := int(binary.LittleEndian.Uint32(b[32:]))
	if hs < 40 || hs > len(b) {
		return nil, errors.New("intestazione bitmap non valida")
	}
	top := false
	if h < 0 {
		h, top = -h, true
	}
	if w <= 0 || h <= 0 || w > 16384 || h > 16384 {
		return nil, errors.New("dimensioni bitmap non valide")
	}
	if (bits != 24 && bits != 32) || (comp != 0 && comp != 3) {
		return nil, fmt.Errorf("formato bitmap non gestito (%d bit, compressione %d)", bits, comp)
	}
	off := hs
	if comp == 3 && hs == 40 {
		off += 12 // maschere dei colori
	}
	off += clr * 4
	stride := ((w*bits + 31) / 32) * 4
	if off+stride*h > len(b) {
		return nil, errors.New("dati bitmap incompleti")
	}
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	for y := 0; y < h; y++ {
		sy := h - 1 - y
		if top {
			sy = y
		}
		row := b[off+sy*stride:]
		for x := 0; x < w; x++ {
			if bits == 24 {
				p := row[x*3:]
				img.SetRGBA(x, y, color.RGBA{p[2], p[1], p[0], 255})
			} else {
				p := row[x*4:]
				img.SetRGBA(x, y, color.RGBA{p[2], p[1], p[0], 255}) // l'alfa dagli appunti spesso è 0: si ignora
			}
		}
	}
	return img, nil
}

// fitSize: dimensioni che stanno nel riquadro senza ingrandire.
func fitSize(w, h, maxW, maxH int) (int, int) {
	if w <= maxW && h <= maxH {
		return w, h
	}
	fw, fh := float64(maxW)/float64(w), float64(maxH)/float64(h)
	f := fw
	if fh < f {
		f = fh
	}
	nw, nh := int(float64(w)*f), int(float64(h)*f)
	if nw < 1 {
		nw = 1
	}
	if nh < 1 {
		nh = 1
	}
	return nw, nh
}

// scaleTo riduce con media sui blocchi (buona resa per screenshot e testo). Non ingrandisce.
func scaleTo(src image.Image, maxW, maxH int) *image.RGBA {
	sb := src.Bounds()
	sw, sh := sb.Dx(), sb.Dy()
	dw, dh := fitSize(sw, sh, maxW, maxH)
	// sfondo bianco: PNG con trasparenza
	flat := image.NewRGBA(image.Rect(0, 0, sw, sh))
	draw.Draw(flat, flat.Bounds(), image.NewUniform(color.White), image.Point{}, draw.Src)
	draw.Draw(flat, flat.Bounds(), src, sb.Min, draw.Over)
	if dw == sw && dh == sh {
		return flat
	}
	dst := image.NewRGBA(image.Rect(0, 0, dw, dh))
	for y := 0; y < dh; y++ {
		y0, y1 := y*sh/dh, (y+1)*sh/dh
		if y1 <= y0 {
			y1 = y0 + 1
		}
		for x := 0; x < dw; x++ {
			x0, x1 := x*sw/dw, (x+1)*sw/dw
			if x1 <= x0 {
				x1 = x0 + 1
			}
			var r, g, b, n int
			for yy := y0; yy < y1; yy++ {
				base := yy*flat.Stride + x0*4
				for xx := x0; xx < x1; xx++ {
					r += int(flat.Pix[base])
					g += int(flat.Pix[base+1])
					b += int(flat.Pix[base+2])
					base += 4
					n++
				}
			}
			o := y*dst.Stride + x*4
			dst.Pix[o], dst.Pix[o+1], dst.Pix[o+2], dst.Pix[o+3] = byte(r/n), byte(g/n), byte(b/n), 255
		}
	}
	return dst
}

func encodePNG(img image.Image) ([]byte, error) {
	var buf bytes.Buffer
	enc := png.Encoder{CompressionLevel: png.BestSpeed}
	if err := enc.Encode(&buf, img); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// bgra: pixel nell'ordine che si aspetta GDI (blu, verde, rosso, alfa), dall'alto in basso.
func bgra(img *image.RGBA) []byte {
	w, h := img.Bounds().Dx(), img.Bounds().Dy()
	out := make([]byte, w*h*4)
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			s := y*img.Stride + x*4
			d := (y*w + x) * 4
			out[d], out[d+1], out[d+2], out[d+3] = img.Pix[s+2], img.Pix[s+1], img.Pix[s], 255
		}
	}
	return out
}

// thumbRTF: frammento RTF con l'immagine a dimensione ridotta, da inserire nella chat. Si usa \dibitmap0 (bitmap a 24 bit senza
// intestazione di file) e non \pngblip: RichEdit riserva lo spazio per un PNG ma su alcune versioni di Windows non lo disegna.
// \picw/\pich sono in centesimi di millimetro (96 dpi), \picwgoal/\pichgoal in twip.
func thumbRTF(img *image.RGBA) string {
	w, h := img.Bounds().Dx(), img.Bounds().Dy()
	rb := (w*3 + 3) &^ 3 // righe di 24 bit allineate a 4 byte
	var sb strings.Builder
	fmt.Fprintf(&sb, `{\rtf1{\pict\dibitmap0\wbmbitspixel24\wbmplanes1\wbmwidthbytes%d\picw%d\pich%d\picwgoal%d\pichgoal%d `, rb, w*2646/100, h*2646/100, w*15, h*15)
	const hexd = "0123456789abcdef"
	put := func(b ...byte) {
		for _, c := range b {
			sb.WriteByte(hexd[c>>4])
			sb.WriteByte(hexd[c&15])
		}
	}
	le32 := func(v int) []byte { return []byte{byte(v), byte(v >> 8), byte(v >> 16), byte(v >> 24)} }
	put(le32(40)...) // BITMAPINFOHEADER
	put(le32(w)...)
	put(le32(h)...)  // altezza positiva: righe dal basso
	put(1, 0, 24, 0) // piani, bit per pixel
	put(le32(0)...)  // BI_RGB
	put(le32(rb * h)...)
	put(le32(2835)...)
	put(le32(2835)...)
	put(le32(0)...)
	put(le32(0)...)
	pad := make([]byte, rb-w*3)
	for y := h - 1; y >= 0; y-- {
		for x := 0; x < w; x++ {
			o := y*img.Stride + x*4
			put(img.Pix[o+2], img.Pix[o+1], img.Pix[o]) // blu, verde, rosso
		}
		put(pad...)
	}
	sb.WriteString("}\\par}")
	return sb.String()
}

// decodeAny: PNG, JPEG o GIF.
func decodeAny(b []byte) (image.Image, error) {
	img, _, err := image.Decode(bytes.NewReader(b))
	return img, err
}
