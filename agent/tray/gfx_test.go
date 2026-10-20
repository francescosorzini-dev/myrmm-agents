package main

import (
	"bytes"
	"encoding/binary"
	"image"
	"image/color"
	"strings"
	"testing"
)

func mkDIB(w, h, bits int, topDown bool) []byte {
	stride := ((w*bits + 31) / 32) * 4
	hdr := make([]byte, 40)
	binary.LittleEndian.PutUint32(hdr[0:], 40)
	binary.LittleEndian.PutUint32(hdr[4:], uint32(w))
	hh := int32(h)
	if topDown {
		hh = -hh
	}
	binary.LittleEndian.PutUint32(hdr[8:], uint32(hh))
	binary.LittleEndian.PutUint16(hdr[12:], 1)
	binary.LittleEndian.PutUint16(hdr[14:], uint16(bits))
	pix := make([]byte, stride*h)
	// riga in memoria 0: pixel (0,*) rosso; ultima riga: blu
	for r := 0; r < h; r++ {
		for x := 0; x < w; x++ {
			o := r*stride + x*bits/8
			if r == 0 {
				pix[o+2] = 255 // R
			} else if r == h-1 {
				pix[o] = 255 // B
			}
		}
	}
	return append(hdr, pix...)
}

func TestDIBBottomUpAndTopDown(t *testing.T) {
	for _, bits := range []int{24, 32} {
		img, err := dibToImage(mkDIB(5, 3, bits, false)) // bottom-up: riga 0 in memoria = ultima riga dell'immagine
		if err != nil {
			t.Fatal(err)
		}
		if c := img.RGBAAt(0, 2); c != (color.RGBA{255, 0, 0, 255}) {
			t.Errorf("%d bit bottom-up: in basso atteso rosso, trovato %v", bits, c)
		}
		if c := img.RGBAAt(0, 0); c != (color.RGBA{0, 0, 255, 255}) {
			t.Errorf("%d bit bottom-up: in alto atteso blu, trovato %v", bits, c)
		}
		img, _ = dibToImage(mkDIB(5, 3, bits, true))
		if c := img.RGBAAt(0, 0); c != (color.RGBA{255, 0, 0, 255}) {
			t.Errorf("%d bit top-down: in alto atteso rosso, trovato %v", bits, c)
		}
	}
	if _, err := dibToImage([]byte{1, 2, 3}); err == nil {
		t.Error("una bitmap troncata deve dare errore")
	}
	bad := mkDIB(5, 3, 24, false)
	if _, err := dibToImage(bad[:60]); err == nil {
		t.Error("dati incompleti devono dare errore")
	}
	huge := mkDIB(2, 2, 24, false)
	binary.LittleEndian.PutUint32(huge[4:], 100000)
	if _, err := dibToImage(huge); err == nil {
		t.Error("dimensioni assurde devono dare errore")
	}
}

func TestScaleAndFit(t *testing.T) {
	src := image.NewRGBA(image.Rect(0, 0, 400, 200))
	for i := range src.Pix {
		src.Pix[i] = 255
	}
	d := scaleTo(src, 100, 100)
	if d.Bounds().Dx() != 100 || d.Bounds().Dy() != 50 {
		t.Errorf("riduzione: %v", d.Bounds())
	}
	if d := scaleTo(src, 1000, 1000); d.Bounds().Dx() != 400 {
		t.Error("non deve ingrandire")
	}
	if w, h := fitSize(3, 3000, 100, 100); w < 1 || h != 100 {
		t.Errorf("fitSize estremo: %d x %d", w, h)
	}
}

func TestPNGAndRTF(t *testing.T) {
	src := image.NewRGBA(image.Rect(0, 0, 8, 8))
	b, err := encodePNG(src)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := decodeAny(b); err != nil {
		t.Fatal(err)
	}
	r := thumbRTF(b, 8, 8)
	if !strings.HasPrefix(r, `{\rtf1{\pict\pngblip`) || !strings.Contains(r, `\picwgoal120`) || !strings.HasSuffix(r, `\par}`) {
		t.Errorf("rtf: %.80s", r)
	}
	if bg := bgra(src); len(bg) != 8*8*4 || bg[3] != 255 {
		t.Error("bgra")
	}
	if _, err := decodeAny(bytes.Repeat([]byte{1}, 20)); err == nil {
		t.Error("dati non immagine devono dare errore")
	}
}
