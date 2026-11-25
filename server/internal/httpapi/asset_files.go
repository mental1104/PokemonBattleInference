package httpapi

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

// spriteFile 描述一份数据库已登记的外部正文；路径相对于其固定Git版本的sprites目录。
// 摘要和长度来自完整快照扫描，HTTP层只核验字节，不重新推导路径分类或选图规则。
type spriteFile struct {
	SourceCommit string
	RelativePath string
	Digest       string
	ByteSize     int64
}

// validateSpriteFileRoot 接受显式绝对快照父目录，返回解析符号链接后的目录；空值表示仅使用旧BYTEA。
// 不创建目录、不下载素材；缺失或不是目录时失败，使实际进程在接流量之前拒绝错误挂载。
func validateSpriteFileRoot(root string) (string, error) {
	if root == "" {
		return "", nil
	}
	if !filepath.IsAbs(root) {
		return "", errors.New("sprite filesystem root must be absolute")
	}
	resolved, err := filepath.EvalSymlinks(root)
	if err != nil {
		return "", err
	}
	info, err := os.Stat(resolved)
	if err != nil {
		return "", err
	}
	if !info.IsDir() {
		return "", errors.New("sprite filesystem root is not a directory")
	}
	return resolved, nil
}

// readSpriteFile 读取root/<commit>/sprites/<relative>，仅返回大小和SHA全部匹配的真实正文。
// ctx取消即失败；root由构造函数核验，asset来自PG。越界路径、逃逸symlink、缺失或损坏均返回错误。
// 目录由部署方只读挂载，版本快照保留至不再被数据库引用；本函数从不修改或删除文件。
func readSpriteFile(ctx context.Context, root string, asset spriteFile) ([]byte, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if root == "" || len(asset.SourceCommit) != 40 || asset.SourceCommit != strings.ToLower(asset.SourceCommit) || !fs.ValidPath(asset.RelativePath) || asset.RelativePath == "." || asset.ByteSize < 0 {
		return nil, errors.New("invalid sprite file metadata or missing filesystem root")
	}
	if _, err := hex.DecodeString(asset.SourceCommit); err != nil {
		return nil, errors.New("invalid sprite source commit")
	}
	filename := filepath.Join(root, asset.SourceCommit, "sprites", filepath.FromSlash(asset.RelativePath))
	resolved, err := filepath.EvalSymlinks(filename)
	if err != nil {
		return nil, err
	}
	local, err := filepath.Rel(root, resolved)
	if err != nil || !filepath.IsLocal(local) {
		return nil, errors.New("sprite file escapes its configured root")
	}
	file, err := os.Open(resolved)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Size() != asset.ByteSize {
		return nil, errors.New("sprite file size or type differs from its manifest")
	}
	// 限定读取到登记长度；额外一个字节用于识别stat之后的增长，不把损坏文件无限读进内存。
	content, err := io.ReadAll(io.LimitReader(file, asset.ByteSize))
	if err != nil {
		return nil, err
	}
	var extra [1]byte
	count, tailErr := file.Read(extra[:])
	if count != 0 || (tailErr != nil && !errors.Is(tailErr, io.EOF)) {
		return nil, errors.New("sprite file changed during reading")
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	digest := sha256.Sum256(content)
	if int64(len(content)) != asset.ByteSize || hex.EncodeToString(digest[:]) != asset.Digest {
		return nil, errors.New("sprite file checksum differs from its manifest")
	}
	return content, nil
}
