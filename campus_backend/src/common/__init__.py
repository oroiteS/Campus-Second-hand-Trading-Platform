"""横切件：统一响应封装、错误码表、分页助手、Swagger 文档路由装配。

common/ 只被 router / routes / services 引用，禁止反向依赖它们，
也不得包含业务逻辑。
"""
