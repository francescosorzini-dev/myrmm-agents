package main

// Chiave della sonda per le credenziali di distribuzione: il server cifra la password con la chiave PUBBLICA della sonda
// (libsodium «sealed box»), quindi può leggerla solo la sonda; il server non la conserva (a meno che l'amministratore non
// abbia abilitato il salvataggio cifrato per cliente). La chiave privata resta nella cartella dati dell'agent (0600).

import (
	"crypto/rand"
	"encoding/base64"
	"errors"
	"os"
	"path/filepath"
	"sync"

	"golang.org/x/crypto/nacl/box"
)

var probeKey struct {
	sync.Mutex
	pub, priv *[32]byte
}

func probeKeyPath() string { return filepath.Join(dataDir(), "probe.key") }

// probeKeys carica (o crea) la coppia di chiavi della sonda.
func probeKeys() (*[32]byte, *[32]byte, error) {
	probeKey.Lock()
	defer probeKey.Unlock()
	if probeKey.pub != nil {
		return probeKey.pub, probeKey.priv, nil
	}
	if b, err := os.ReadFile(probeKeyPath()); err == nil && len(b) == 64 {
		var pub, priv [32]byte
		copy(priv[:], b[:32])
		copy(pub[:], b[32:])
		probeKey.pub, probeKey.priv = &pub, &priv
		return &pub, &priv, nil
	}
	pub, priv, err := box.GenerateKey(rand.Reader)
	if err != nil {
		return nil, nil, err
	}
	if err := os.MkdirAll(dataDir(), 0o700); err == nil {
		err = os.WriteFile(probeKeyPath(), append(priv[:], pub[:]...), 0o600)
	}
	probeKey.pub, probeKey.priv = pub, priv
	return pub, priv, nil
}

// probePubB64: chiave pubblica (base64) da inviare al server; vuota se non disponibile.
func probePubB64() string {
	pub, _, err := probeKeys()
	if err != nil {
		return ""
	}
	return base64.StdEncoding.EncodeToString(pub[:])
}

// openSealed decifra un messaggio cifrato dal server per questa sonda.
func openSealed(b64 string) ([]byte, error) {
	raw, err := base64.StdEncoding.DecodeString(b64)
	if err != nil {
		return nil, err
	}
	pub, priv, err := probeKeys()
	if err != nil {
		return nil, err
	}
	out, ok := box.OpenAnonymous(nil, raw, pub, priv)
	if !ok {
		return nil, errors.New("credenziali non decifrabili (chiave della sonda cambiata?)")
	}
	return out, nil
}
