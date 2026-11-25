package knowledge

import (
	"fmt"
	"mime"
	"path"
	"strconv"
	"strings"
	"unicode"
)

// spriteMetadata 保存原 SpritePathMetadata 的完整可空字段；原始路径与不能识别的资产也保留。
// 这里只解析资源路径，不决定 ruleset 选图优先级，选图仍由原 PostgreSQL MV 负责。
type spriteMetadata struct {
	RelativePath string
	Category     string
	PokemonID    *int64
	Generation   *string
	Version      *string
	Collection   *string
	RenderStyle  *string
	Slot         *string
	Front        *bool
	Back         *bool
	Female       *bool
	Shiny        *bool
	Animated     *bool
	Status       string
}

// spriteValue 返回 value 的独立指针，用于表达 SQL NULL 与显式 false/空值的区别。
func spriteValue[T any](value T) *T { return &value }

// spriteDigit 把 Unicode Nd 数字转换成十进制值，保持原 Python 正则 \d 和 int 的语义。
// character 是单个文件名字符；非十进制数字返回 -1，不把其他 Unicode 数字当成 ID。
func spriteDigit(character rune) int {
	for _, item := range unicode.Nd.R16 {
		if character >= rune(item.Lo) && character <= rune(item.Hi) && (character-rune(item.Lo))%rune(item.Stride) == 0 {
			return int((character-rune(item.Lo))/rune(item.Stride)) % 10
		}
	}
	for _, item := range unicode.Nd.R32 {
		if character >= rune(item.Lo) && character <= rune(item.Hi) && (character-rune(item.Lo))%rune(item.Stride) == 0 {
			return int((character-rune(item.Lo))/rune(item.Stride)) % 10
		}
	}
	return -1
}

// spritePokemonID 识别原数字前缀及 -_. 变体名；stem 不含最后扩展名。
// 无映射返回 nil；超出数据库整数可表示范围的输入返回错误，不能悄悄改为无映射。
func spritePokemonID(stem string) (*int64, error) {
	stem = strings.TrimSuffix(stem, "\n") // Python 正则的 $ 允许一个最终换行。
	var digits strings.Builder
	end := 0
	for index, character := range stem {
		digit := spriteDigit(character)
		if digit < 0 {
			break
		}
		digits.WriteByte(byte('0' + digit))
		end = index + len(string(character))
	}
	if digits.Len() == 0 {
		return nil, nil
	}
	remainder := stem[end:]
	if remainder != "" && (strings.Contains(remainder, "\n") || !strings.ContainsRune("-_.", rune(remainder[0]))) {
		return nil, nil
	}
	value, err := strconv.ParseInt(digits.String(), 10, 32)
	if err != nil {
		return nil, fmt.Errorf("sprite Pokemon identifier exceeds PostgreSQL integer: %w", err)
	}
	return &value, nil
}

// parseSpritePath 将受控源中的 POSIX 相对路径投影为原导入元数据；不丢弃 unparsed 文件。
// relative 必须是扫描器生成的相对路径；返回新值，整数溢出时显式失败。
func parseSpritePath(relative string) (spriteMetadata, error) {
	parts := strings.Split(relative, "/")
	result := spriteMetadata{RelativePath: relative, Category: parts[0], Status: "unparsed"}
	base := path.Base(relative)
	extension := path.Ext(base)
	if extension == "." || extension == base {
		extension = ""
	}
	if result.Category != "pokemon" || extension == "" {
		return result, nil
	}
	identifier, err := spritePokemonID(strings.TrimSuffix(base, extension))
	if err != nil {
		return result, err
	}
	result.PokemonID = identifier
	result.Collection = spriteValue("pokemon")
	if len(parts) >= 4 && parts[1] == "other" {
		result.Collection, result.RenderStyle = spriteValue("other"), spriteValue(parts[2])
	} else if len(parts) >= 5 && parts[1] == "versions" {
		result.Collection, result.Generation, result.Version = spriteValue("versions"), spriteValue(parts[2]), spriteValue(parts[3])
		if parts[4] == "animated" {
			result.RenderStyle = spriteValue("animated")
		}
	}
	if identifier == nil {
		return result, nil
	}
	back, female, shiny, animated := false, false, false, strings.EqualFold(extension, ".gif")
	for _, part := range parts {
		back = back || part == "back"
		female = female || part == "female"
		shiny = shiny || part == "shiny"
		animated = animated || part == "animated"
	}
	slot := "front"
	if back {
		slot = "back"
	}
	if female {
		slot += "_female"
	}
	if shiny {
		slot += "_shiny"
	}
	if !female && !shiny {
		slot += "_default"
	}
	result.Front, result.Back, result.Female, result.Shiny, result.Animated = spriteValue(!back), spriteValue(back), spriteValue(female), spriteValue(shiny), spriteValue(animated)
	result.Slot, result.Status = spriteValue(slot), "parsed"
	return result, nil
}

// spriteMIME 使用文件扩展名而非字节嗅探，保留原 mimetypes 的无 charset MIME 合同。
// relative 是受控源路径；未知扩展名回退 application/octet-stream。
func spriteMIME(relative string) string {
	extension := path.Ext(relative)
	if extension == ".gz" || extension == ".bz2" || extension == ".xz" || extension == ".Z" {
		extension = path.Ext(strings.TrimSuffix(relative, extension))
	}
	if extension == ".svgz" {
		return "image/svg+xml"
	}
	// scratch/精简维护镜像可能没有 /etc/mime.types；原 Python 内置的常用源类型不能因此变为二进制。
	switch strings.ToLower(extension) {
	case ".png":
		return "image/png"
	case ".gif":
		return "image/gif"
	case ".jpg", ".jpeg":
		return "image/jpeg"
	case ".webp":
		return "image/webp"
	case ".svg":
		return "image/svg+xml"
	case ".txt":
		return "text/plain"
	case ".json":
		return "application/json"
	}
	value := mime.TypeByExtension(extension)
	if value == "" {
		return "application/octet-stream"
	}
	return strings.TrimSpace(strings.SplitN(value, ";", 2)[0])
}
