package main

import (
	"testing"
	"time"
)

// Dopo un errore l'auto-update riprova con attese crescenti (1,2,5,10,30,60 min) e non resta fermo un'ora intera.
func TestUpdDelay(t *testing.T) {
	want := []time.Duration{0, time.Minute, 2 * time.Minute, 5 * time.Minute, 10 * time.Minute, 30 * time.Minute, time.Hour, time.Hour}
	for i, w := range want {
		if g := updDelay(i); g != w {
			t.Errorf("updDelay(%d) = %v, atteso %v", i, g, w)
		}
	}
}

func TestUpdFailBackoffAndReset(t *testing.T) {
	updFails, updNextTry = 0, time.Time{}
	updFail()
	if d := time.Until(updNextTry); d <= 0 || d > time.Minute {
		t.Fatalf("primo errore: attesa %v, attesa ~1 minuto", d)
	}
	updFail()
	if d := time.Until(updNextTry); d < time.Minute || d > 2*time.Minute {
		t.Fatalf("secondo errore: attesa %v, attesa ~2 minuti", d)
	}
	updFails, updNextTry = 0, time.Time{}
}
