# 本地凭据表单验证

从仓库根目录运行 node frontend/tests/local-geo-evidence/server.mjs，打开 http://127.0.0.1:5278/tests/local-geo-credentials/index.html。

仅挂载真实凭据组件，不发送请求或保存凭据。验证微信原生与网关字段切换、密钥输入遮罩。完整字段构造与错误条件见 frontend/tests/geo-account-credentials.test.mjs。
