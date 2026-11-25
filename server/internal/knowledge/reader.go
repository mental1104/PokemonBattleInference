package knowledge

import (
	"bufio"
	"io"
	"strings"
)

// legacyCSVReader 精确保留原 Python csv.DictReader(strict=False, skipinitialspace=False) 的解析语义。
// 固定资料含“已闭引号后接未引用文本”，Go encoding/csv 的 LazyQuotes 会给出不同字段值。
// 该读取器只在数据导入边界使用；全部 177 份结果必须匹配 Python 导出的逐值 SHA。
type legacyCSVReader struct{ input *bufio.Reader }

// newLegacyCSVReader 借用 input 建立有界缓冲，不读取整个 CSV，也不关闭来源文件。
func newLegacyCSVReader(input io.Reader) *legacyCSVReader {
	return &legacyCSVReader{bufio.NewReaderSize(input, 64<<10)}
}

// csvState 对应原宽松解析的字段起始、普通、已引用和引用后四种有限状态。
type csvState uint8

const (
	csvStart csvState = iota
	csvPlain
	csvQuoted
	csvAfterQuote
)

// Read 返回下一条非空记录；保留引用字段中的 CR/LF，普通记录支持 LF、CR、CRLF。
// EOF 时不完整引用按原 strict=False 收口；读取错误返回原 io 错误，字节数据不做猜测修复。
func (reader *legacyCSVReader) Read() ([]string, error) {
	for {
		fields := make([]string, 0, 8)
		var field strings.Builder
		state := csvStart
		started := false
		for {
			ch, err := reader.input.ReadByte()
			if err == io.EOF {
				if !started {
					return nil, io.EOF
				}
				return append(fields, field.String()), nil
			}
			if err != nil {
				return nil, err
			}
			if state == csvQuoted {
				started = true
				if ch == '"' {
					state = csvAfterQuote
				} else {
					field.WriteByte(ch)
				}
				continue
			}
			// 引用后的双引号代表字段内容；其余非分隔字符进入普通字段，原闭引号不进入正文。
			if state == csvAfterQuote && ch == '"' {
				field.WriteByte('"')
				state = csvQuoted
				continue
			}
			if ch == '\n' || ch == '\r' {
				if ch == '\r' {
					if next, peekErr := reader.input.Peek(1); peekErr == nil && next[0] == '\n' {
						_, _ = reader.input.Discard(1)
					}
				}
				if !started {
					break
				}
				return append(fields, field.String()), nil
			}
			if ch == ',' {
				started = true
				fields = append(fields, field.String())
				field.Reset()
				state = csvStart
				continue
			}
			if state == csvStart && ch == '"' {
				started = true
				state = csvQuoted
				continue
			}
			started = true
			field.WriteByte(ch)
			state = csvPlain
		}
	}
}
