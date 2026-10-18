package main

// JSON con l'ordine delle chiavi conservato: le risposte dell'API arrivano all'assistente nello stesso ordine
// in cui le scrive il server (come faceva la versione Python), senza dipendenze esterne.

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"strconv"
	"strings"
)

type omap struct {
	keys []string
	m    map[string]any
}

func newMap(kv ...any) *omap {
	o := &omap{m: map[string]any{}}
	for i := 0; i+1 < len(kv); i += 2 {
		o.set(kv[i].(string), kv[i+1])
	}
	return o
}

func (o *omap) set(k string, v any) {
	if _, ok := o.m[k]; !ok {
		o.keys = append(o.keys, k)
	}
	o.m[k] = v
}

func (o *omap) get(k string) (any, bool) {
	if o == nil {
		return nil, false
	}
	v, ok := o.m[k]
	return v, ok
}

func (o *omap) val(k string) any {
	v, _ := o.get(k)
	return v
}

func (o *omap) str(k string) string {
	if s, ok := o.val(k).(string); ok {
		return s
	}
	return ""
}

// parseJSON legge un valore JSON completo (nessun testo dopo): oggetti -> *omap, array -> []any, numeri -> json.Number.
func parseJSON(data []byte) (any, error) {
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	v, err := parseValue(dec)
	if err != nil {
		return nil, err
	}
	if _, err := dec.Token(); err != io.EOF {
		return nil, errors.New("testo dopo il valore JSON")
	}
	return v, nil
}

func parseValue(dec *json.Decoder) (any, error) {
	t, err := dec.Token()
	if err != nil {
		return nil, err
	}
	d, ok := t.(json.Delim)
	if !ok {
		return t, nil // stringa, numero, bool, null
	}
	switch d {
	case '{':
		o := newMap()
		for dec.More() {
			kt, err := dec.Token()
			if err != nil {
				return nil, err
			}
			v, err := parseValue(dec)
			if err != nil {
				return nil, err
			}
			o.set(kt.(string), v)
		}
		if _, err := dec.Token(); err != nil {
			return nil, err
		}
		return o, nil
	case '[':
		arr := []any{}
		for dec.More() {
			v, err := parseValue(dec)
			if err != nil {
				return nil, err
			}
			arr = append(arr, v)
		}
		if _, err := dec.Token(); err != nil {
			return nil, err
		}
		return arr, nil
	}
	return nil, errors.New("JSON non valido")
}

func writeString(b *bytes.Buffer, s string) {
	var t bytes.Buffer
	enc := json.NewEncoder(&t)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(s)
	b.Write(bytes.TrimRight(t.Bytes(), "\n"))
}

// writeJSON scrive v; con indent=true usa un rientro di uno spazio per livello (come json.dumps(indent=1)).
func writeJSON(b *bytes.Buffer, v any, indent bool, depth int) {
	nl := func(d int) {
		if indent {
			b.WriteByte('\n')
			b.WriteString(strings.Repeat(" ", d))
		}
	}
	switch x := v.(type) {
	case nil:
		b.WriteString("null")
	case bool:
		if x {
			b.WriteString("true")
		} else {
			b.WriteString("false")
		}
	case string:
		writeString(b, x)
	case json.Number:
		b.WriteString(x.String())
	case int:
		b.WriteString(strconv.Itoa(x))
	case *omap:
		if len(x.keys) == 0 {
			b.WriteString("{}")
			return
		}
		b.WriteByte('{')
		for i, k := range x.keys {
			if i > 0 {
				b.WriteByte(',')
			}
			nl(depth + 1)
			writeString(b, k)
			b.WriteByte(':')
			if indent {
				b.WriteByte(' ')
			}
			writeJSON(b, x.m[k], indent, depth+1)
		}
		nl(depth)
		b.WriteByte('}')
	case []any:
		if len(x) == 0 {
			b.WriteString("[]")
			return
		}
		b.WriteByte('[')
		for i, e := range x {
			if i > 0 {
				b.WriteByte(',')
			}
			nl(depth + 1)
			writeJSON(b, e, indent, depth+1)
		}
		nl(depth)
		b.WriteByte(']')
	case []string:
		a := make([]any, len(x))
		for i, s := range x {
			a[i] = s
		}
		writeJSON(b, a, indent, depth)
	default:
		raw, _ := json.Marshal(x)
		b.Write(raw)
	}
}

func toJSON(v any, indent bool) string {
	var b bytes.Buffer
	writeJSON(&b, v, indent, 0)
	return b.String()
}
