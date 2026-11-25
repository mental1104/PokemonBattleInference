package knowledge

import (
	"bufio"
	"encoding/json"
	"os"
	"reflect"
	"strings"
	"testing"
)

// spritePathReference 对应原Python dataclass导出的JSONL边界，保留NULL与显式false的区别。
// 这里只声明跨语言参考字段，不复制路径解析规则；实际值仍调用生产parseSpritePath。
type spritePathReference struct {
	Metadata struct {
		RelativePath string  `json:"relative_path"`
		Category     string  `json:"asset_category"`
		PokemonID    *int64  `json:"pokemon_id"`
		Generation   *string `json:"generation_identifier"`
		Version      *string `json:"version_identifier"`
		Collection   *string `json:"collection"`
		RenderStyle  *string `json:"render_style"`
		Slot         *string `json:"sprite_slot"`
		Front        *bool   `json:"is_front"`
		Back         *bool   `json:"is_back"`
		Female       *bool   `json:"is_female"`
		Shiny        *bool   `json:"is_shiny"`
		Animated     *bool   `json:"is_animated"`
		Status       string  `json:"parse_status"`
	} `json:"metadata"`
	MIME string `json:"mime_type"`
}

// TestSpritePathsFullPythonReference 逐字段比较固定来源全部路径与原Python参考，不需要PG或图片正文。
// t为测试上下文；PBI_TEST_SPRITE_REFERENCE_JSONL缺省明确SKIP，显式文件错误/任一差异直接失败。
func TestSpritePathsFullPythonReference(t *testing.T) {
	filename := os.Getenv("PBI_TEST_SPRITE_REFERENCE_JSONL")
	if filename == "" {
		t.Skip("set PBI_TEST_SPRITE_REFERENCE_JSONL to export_sprite_path_reference.py output for the full fixed Git tree")
	}
	file, err := os.Open(filename)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	seen := make(map[string]bool)
	for scanner.Scan() {
		var reference spritePathReference
		decoder := json.NewDecoder(strings.NewReader(scanner.Text()))
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(&reference); err != nil {
			t.Fatalf("invalid reference record %d: %v", len(seen)+1, err)
		}
		metadata := reference.Metadata
		if seen[metadata.RelativePath] {
			t.Fatalf("duplicate reference path %q", metadata.RelativePath)
		}
		seen[metadata.RelativePath] = true
		// 仅把原字段映射到既有Go值模型；两个解析器独立执行，不能从Go结果生成预期。
		want := spriteMetadata{
			RelativePath: metadata.RelativePath, Category: metadata.Category, PokemonID: metadata.PokemonID,
			Generation: metadata.Generation, Version: metadata.Version, Collection: metadata.Collection,
			RenderStyle: metadata.RenderStyle, Slot: metadata.Slot, Front: metadata.Front, Back: metadata.Back,
			Female: metadata.Female, Shiny: metadata.Shiny, Animated: metadata.Animated, Status: metadata.Status,
		}
		got, err := parseSpritePath(metadata.RelativePath)
		if err != nil || !reflect.DeepEqual(got, want) {
			actualJSON, _ := json.Marshal(got)
			expectedJSON, _ := json.Marshal(want)
			t.Fatalf("metadata mismatch path=%q got=%s want=%s err=%v", metadata.RelativePath, actualJSON, expectedJSON, err)
		}
		if gotMIME := spriteMIME(metadata.RelativePath); gotMIME != reference.MIME {
			t.Fatalf("MIME mismatch path=%q got=%q want=%q", metadata.RelativePath, gotMIME, reference.MIME)
		}
	}
	if err := scanner.Err(); err != nil {
		t.Fatal(err)
	}
	if len(seen) == 0 {
		t.Fatal("empty sprite reference cannot prove full-source compatibility")
	}
	t.Logf("Verified %d unique sprite paths: all metadata fields and MIME match original Python", len(seen))
}
