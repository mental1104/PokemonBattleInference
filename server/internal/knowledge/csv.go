package knowledge

import (
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"fmt"
	"hash"
	"io"
	"os"
	"strconv"
	"strings"
)

// csvRows 实现 pgx.CopyFromSource，以有界行缓冲按旧 DAO 语义转换公开 CSV。
type csvRows struct {
	file         *os.File
	reader       *legacyCSVReader
	table        Table
	indices      []int
	values       []any
	err          error
	rows         int64
	semanticHash hash.Hash
}

// openRows 读取 header 并绑定模型列位置；缺少列沿用旧 DAO 的空值默认，不按位置猜测。
func openRows(path string, table Table) (*csvRows, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	reader := newLegacyCSVReader(file)
	header, err := reader.Read()
	if err != nil {
		file.Close()
		return nil, err
	}
	positions := map[string]int{}
	for index, name := range header {
		if _, exists := positions[name]; exists {
			file.Close()
			return nil, errors.New("CSV header contains duplicate columns")
		}
		positions[name] = index
	}
	source := &csvRows{file: file, reader: reader, table: table, indices: make([]int, len(table.Columns)), values: make([]any, len(table.Columns)), semanticHash: sha256.New()}
	for index, column := range table.Columns {
		source.indices[index] = -1
		if position, ok := positions[column.Name]; ok {
			source.indices[index] = position
		}
	}
	return source, nil
}

// Next 读取一行并转换整数/布尔/文本；每次仅持有当前行，错误延迟给 Err。
func (source *csvRows) Next() bool {
	if source.err != nil {
		return false
	}
	record, err := source.reader.Read()
	if errors.Is(err, io.EOF) {
		return false
	}
	if err != nil {
		source.err = err
		return false
	}
	for index, column := range source.table.Columns {
		raw := ""
		if position := source.indices[index]; position >= 0 && position < len(record) {
			raw = record[position]
		}
		switch column.Kind {
		case Integer:
			if raw == "" {
				source.values[index] = int64(0)
			} else {
				value, parseErr := strconv.ParseInt(raw, 10, 64)
				if parseErr != nil {
					source.err = fmt.Errorf("invalid integer in %s.%s", source.table.Name, column.Name)
					return false
				}
				source.values[index] = value
			}
		case Boolean:
			normalized := strings.ToLower(strings.TrimSpace(raw))
			switch normalized {
			case "", "0", "f", "false", "n", "no":
				source.values[index] = false
			default:
				source.values[index] = true
			}
		case Text:
			source.values[index] = raw
		default:
			source.err = errors.New("unsupported CSV column kind")
			return false
		}
	}
	for _, value := range source.values {
		var text string
		switch item := value.(type) {
		case int64:
			text = strconv.FormatInt(item, 10)
		case bool:
			if item {
				text = "1"
			} else {
				text = "0"
			}
		case string:
			text = item
		}
		var size [8]byte
		binary.BigEndian.PutUint64(size[:], uint64(len(text)))
		_, _ = source.semanticHash.Write(size[:])
		_, _ = io.WriteString(source.semanticHash, text)
	}
	source.rows++
	return true
}

// Values 返回当前行；CopyFrom 在下次 Next 前完成编码，不保留接收者的内部缓冲。
func (source *csvRows) Values() ([]any, error) { return source.values, source.err }

// Err 返回读取或转换错误；EOF 表示正常结束而非失败。
func (source *csvRows) Err() error { return source.err }

// Close 释放 source 拥有的 CSV 文件句柄。
func (source *csvRows) Close() error { return source.file.Close() }
