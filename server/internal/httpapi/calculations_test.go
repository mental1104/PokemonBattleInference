package httpapi

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

// TestHTTPCoreRoundTrip 通过真实回环 HTTP 连接调用 CGO/Core，完整比较共享响应。
func TestHTTPCoreRoundTrip(t *testing.T) {
	root := os.Getenv("PBI_CONTRACT_FIXTURES")
	if root == "" {
		root = "../../../tests/vectors"
	}
	request, err := os.ReadFile(filepath.Join(root, "abi-calculations.v1.request.json"))
	if err != nil {
		t.Fatal(err)
	}
	expected, err := os.ReadFile(filepath.Join(root, "abi-calculations.v1.response.json"))
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(Handler())
	defer server.Close()
	response, err := http.Post(server.URL+"/v1/core/calculate", "application/json", bytes.NewReader(request))
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}
	var got, want any
	if err := json.Unmarshal(body, &got); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(expected, &want); err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != 200 || !reflect.DeepEqual(got, want) {
		t.Fatalf("HTTP mismatch: %d %s", response.StatusCode, body)
	}
	bad, err := http.Post(server.URL+"/v1/core/calculate", "application/json", bytes.NewBufferString("{"))
	if err != nil {
		t.Fatal(err)
	}
	defer bad.Body.Close()
	if bad.StatusCode != 400 {
		t.Fatalf("invalid input returned %d", bad.StatusCode)
	}
}
