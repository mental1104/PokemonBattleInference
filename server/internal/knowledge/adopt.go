package knowledge

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"
)

// ErrLegacyMismatch 表示历史知识表的结构或全部字段不等于固定来源，不允许登记版本。
var ErrLegacyMismatch = errors.New("legacy knowledge differs from the fixed schema or data")

// AdoptLegacy 显式核对原Python知识库并登记Go版本；不清空、不重写任何历史raw行。
// ctx控制扫描/锁/SQL取消，dsn必须指向已授权的库，root必须是完整固定CSV源，refresh控制原MV刷新。
// 返回完整核验行数及legacy_adopted标记；不一致或中断时回滚全部版本/schema写入。
func AdoptLegacy(ctx context.Context, dsn, root string, refresh bool) (Report, error) {
	return initialize(ctx, dsn, root, refresh, adoptLegacy)
}

// expectedLegacyDDL 从已校验SHA的固定生成SQL提取一张表，改名为本事务临时表。
// table来自嵌入manifest；返回仅用于自有pg_temp的DDL，不解析外部SQL或复用历史表的约束。
// 生成格式改变时明确拒绝；临时SERIAL使用自己的序列，不会消耗历史库的序列。
func expectedLegacyDDL(table Table) (string, error) {
	prefix := "CREATE TABLE IF NOT EXISTS poke_raw." + table.Name + " ("
	_, definition, found := strings.Cut(rawSchema, prefix)
	if !found {
		return "", fmt.Errorf("fixed schema definition unavailable: %s", table.Name)
	}
	definition, _, found = strings.Cut(definition, "\n);")
	if !found {
		return "", fmt.Errorf("unsupported fixed schema definition: %s", table.Name)
	}
	return "CREATE TEMP TABLE pbi_knowledge_expected (" + definition + "\n) ON COMMIT DROP", nil
}

// verifyLegacyTable 比较一张历史表与固定schema和CSV的完整行集合，绝不只按行数认可。
// ctx/tx控制事务和取消；root/table为已核验来源。返回规范来源行数和已验证的去重后行数。
// SHARE锁持续到事务结束，阻止核对后、登记前的并发写入；临时表每张结束即释放。
func verifyLegacyTable(ctx context.Context, tx pgx.Tx, root string, table Table) (TableReport, error) {
	target := pgx.Identifier{"poke_raw", table.Name}.Sanitize()
	expected := pgx.Identifier{"pg_temp", "pbi_knowledge_expected"}
	report := TableReport{Name: table.Name}
	ddl, err := expectedLegacyDDL(table)
	if err != nil {
		return report, err
	}
	if _, err = tx.Exec(ctx, `LOCK TABLE `+target+` IN SHARE MODE; `+ddl); err != nil {
		return report, err
	}
	// 类型、可空性、列顺序和主键/唯一/CHECK/FK都比较固定模型，不从历史表克隆期望约束。
	var different bool
	for _, projection := range []string{
		`SELECT attname,atttypid,atttypmod,attnotnull,attnum FROM pg_attribute WHERE attrelid=%s::regclass AND attnum>0 AND NOT attisdropped`,
		`SELECT contype,pg_get_constraintdef(oid,true) FROM pg_constraint WHERE conrelid=%s::regclass AND contype IN ('p','u','c','f')`,
	} {
		left, right := fmt.Sprintf(projection, "$1"), fmt.Sprintf(projection, "$2")
		if err = tx.QueryRow(ctx, `SELECT EXISTS((`+left+` EXCEPT `+right+`) UNION ALL (`+right+` EXCEPT `+left+`))`, target, expected.Sanitize()).Scan(&different); err != nil {
			return report, err
		}
		if different {
			return report, fmt.Errorf("%w: %s schema", ErrLegacyMismatch, table.Name)
		}
	}
	report, err = importTableInto(ctx, tx, root, table, expected)
	if err != nil {
		return report, err
	}
	// EXCEPT ALL双向比较保留重复行语义；所有列都由固定manifest明确列举并由驱动转义。
	columns := columnsSQL(table)
	left, right := `SELECT `+columns+` FROM `+target, `SELECT `+columns+` FROM `+expected.Sanitize()
	if err = tx.QueryRow(ctx, `SELECT EXISTS((`+left+` EXCEPT ALL `+right+`) UNION ALL (`+right+` EXCEPT ALL `+left+`))`).Scan(&different); err != nil {
		return report, err
	}
	if different {
		return report, fmt.Errorf("%w: %s data", ErrLegacyMismatch, table.Name)
	}
	_, err = tx.Exec(ctx, `DROP TABLE `+expected.Sanitize())
	return report, err
}
