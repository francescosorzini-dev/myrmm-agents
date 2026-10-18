package main

import "runtime"

func goArch() string { return runtime.GOARCH }

func round1(f float64) float64 { return float64(int(f*10+0.5)) / 10 }
