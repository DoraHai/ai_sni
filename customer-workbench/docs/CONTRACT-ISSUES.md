# phaseLINK 契约变更记录（2026-10-20）

经 task.md 记载的 20:30 批准，替换 v1 的「query 白名单为空」策略；本记录只涉及链接安全投影。

- FE #781 与 BE #782 同步允许普通公开 http(s) query；不改变 GET 请求白名单、鉴权、周指标、来源证据计算或发布行为。
- 先对 URL 解码后的全部参数名检查凭据键，大小写不敏感；命中则整条抑制，url/published_url=null、url_state=suppressed。不通过删除凭据键重新开放。
- 移除 utm_*、gclid、dclid、fbclid、msclkid、spm、yclid、_ga、_gl；普通参数、重复键和空值保留，fragment 移除。
- 凭据名覆盖 token、access_token、accessToken、key、apikey、api_key、secret、password、passwd、pwd、sig、signature、auth、authorization、session、sessionid、session_id、code、credential、credentials、jwt；非字母数字边界的复合名也匹配，如 X-Amz-Signature/client_secret/session[id]。utm_token 仍抑制。
- 保留对非 http(s)、userinfo、IP（含非标准 IPv4 形式）、单标签/内网域名、非 80/443 端口、反斜线/控制字符的拒绝；两端统一 localdomain/intranet/corp/private/onion 等内部域后缀。
- F.citations[] 与 L.publication 新增 domain:string|null，只含经公开域名校验的主机名；安全公开主机即使链接被抑制也可作为不可点击文本。内网/IP/非法协议不返回域名，绝不使用原始 URL 作备用字段。
- is_own_domain 继续由后端按原 host 分类；后端发布计数沿用「published 且安全公开 URL」，现在正常 query 也可满足安全 URL 条件。
- 前端合成 HTTP 快照及 GEO_CLIENT_ALIGNMENT_R2.md 更新至本轮后端提交；全部为 SQLite 内存合成数据，不替代生产联调。
