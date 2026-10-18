module myrmm-agent

go 1.22

require (
	github.com/gosnmp/gosnmp v1.37.0
	github.com/kardianos/service v1.2.2
	golang.org/x/crypto v0.14.0
)

require golang.org/x/sys v0.13.0

// golang.org/x/sys usa un import "vanity" su golang.org (non sempre raggiungibile);
// lo risolviamo direttamente da GitHub. Rimuovi questa riga in un ambiente con GOPROXY standard.
replace golang.org/x/sys => github.com/golang/sys v0.13.0

replace golang.org/x/crypto => github.com/golang/crypto v0.14.0
