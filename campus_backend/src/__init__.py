"""campus_backend 源码包。

分层与依赖方向（flask-backend 规范，单向）：
main → app → router → routes → services → model；common/ 为横切件，
只被 router/routes/services 引用，不反向依赖。
"""
