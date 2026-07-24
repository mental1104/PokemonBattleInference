/**
 * 为 Vitest 下的 CSS 文件合同测试声明最小 Node 文件读取接口。
 *
 * 前端生产代码不依赖 Node；这里只避免为单个只读测试引入整套 `@types/node`。
 */
declare module 'node:fs' {
  /**
   * 以 UTF-8 文本读取仓库内文件。
   *
   * @param path 相对于当前测试工作目录的文件路径。
   * @param encoding 固定为 UTF-8 文本编码。
   * @returns 文件完整文本内容。
   */
  export function readFileSync(path: string, encoding: 'utf8'): string;
}
