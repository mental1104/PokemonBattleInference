package httpapi

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// spriteFileFixture 创建本测试拥有的固定版本目录，返回根、文件元数据与真实正文。
// t拥有目录生命周期；正文只用于验证读盘/完整性，不依赖数据库或外部图片服务。
func spriteFileFixture(t *testing.T) (string, spriteFile, []byte) {
	t.Helper()
	root := t.TempDir()
	content := []byte("owned sprite bytes")
	digest := sha256.Sum256(content)
	asset := spriteFile{SourceCommit: strings.Repeat("a", 40), RelativePath: "pokemon/212.png", Digest: hex.EncodeToString(digest[:]), ByteSize: int64(len(content))}
	filename := filepath.Join(root, asset.SourceCommit, "sprites", asset.RelativePath)
	if err := os.MkdirAll(filepath.Dir(filename), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filename, content, 0600); err != nil {
		t.Fatal(err)
	}
	return root, asset, content
}

// TestSpriteFileReader 验证版本定位、逐字节读取及取消，不将缺失正文视为合法空文件。
func TestSpriteFileReader(t *testing.T) {
	root, asset, content := spriteFileFixture(t)
	resolved, err := validateSpriteFileRoot(root)
	if err != nil {
		t.Fatal(err)
	}
	actual, err := readSpriteFile(context.Background(), resolved, asset)
	if err != nil || string(actual) != string(content) {
		t.Fatalf("file body mismatch: %q %v", actual, err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err = readSpriteFile(ctx, resolved, asset); err == nil {
		t.Fatal("cancelled file read succeeded")
	}
	if _, err = validateSpriteFileRoot("relative-assets"); err == nil {
		t.Fatal("relative filesystem root was accepted")
	}
	if _, err = validateSpriteFileRoot(filepath.Join(root, "missing")); err == nil {
		t.Fatal("missing filesystem root was accepted")
	}
}

// TestSpriteFileReaderRejectsInvalidMetadata 覆盖路径穿越、非法来源/摘要与文件缺失。
// 每个case复制不可变基准元数据，失败不能返回任何正文。
func TestSpriteFileReaderRejectsInvalidMetadata(t *testing.T) {
	root, baseline, _ := spriteFileFixture(t)
	for _, relative := range []string{"", ".", "../secret", "/etc/passwd", "pokemon/../../secret", "pokemon/missing.png"} {
		asset := baseline
		asset.RelativePath = relative
		if body, err := readSpriteFile(context.Background(), root, asset); err == nil || body != nil {
			t.Fatalf("invalid relative path accepted: %q", relative)
		}
	}
	for _, source := range []string{"", "../escape", strings.Repeat("A", 40), strings.Repeat("z", 40)} {
		asset := baseline
		asset.SourceCommit = source
		if _, err := readSpriteFile(context.Background(), root, asset); err == nil {
			t.Fatalf("invalid source commit accepted: %q", source)
		}
	}
	asset := baseline
	asset.Digest = strings.Repeat("0", 64)
	if _, err := readSpriteFile(context.Background(), root, asset); err == nil {
		t.Fatal("incorrect checksum was accepted")
	}
	asset = baseline
	asset.ByteSize++
	if _, err := readSpriteFile(context.Background(), root, asset); err == nil {
		t.Fatal("incorrect size was accepted")
	}
}

// TestSpriteFileReaderRejectsEscapingSymlink 用摘要完全正确的外部文件证明不能逃出配置根。
func TestSpriteFileReaderRejectsEscapingSymlink(t *testing.T) {
	root, asset, content := spriteFileFixture(t)
	outside := filepath.Join(t.TempDir(), "outside.png")
	if err := os.WriteFile(outside, content, 0600); err != nil {
		t.Fatal(err)
	}
	filename := filepath.Join(root, asset.SourceCommit, "sprites", asset.RelativePath)
	if err := os.Remove(filename); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filename); err != nil {
		t.Fatal(err)
	}
	if _, err := readSpriteFile(context.Background(), root, asset); err == nil {
		t.Fatal("escaping symlink was accepted")
	}
}
