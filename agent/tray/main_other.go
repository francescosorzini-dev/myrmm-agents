//go:build !windows

package main

import (
	"fmt"
	"os"
)

func main() {
	fmt.Fprintln(os.Stderr, "myrmm-tray esiste solo per Windows")
	os.Exit(1)
}
