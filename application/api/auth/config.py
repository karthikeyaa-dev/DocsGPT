class CONFIG:

    # --------DB_Credentials--------#
    PG_USERNAME = "user"
    PG_PASSWORD = "password"
    PG_DATABASENAME = "docsgpt"
    PG_HOST = "localhost"
    PG_PORT = 5432

    # ------Encode_Credentials------#
    JWT_SECRET_KEY = "fuck-you-nvidea"
    JWT_ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_IN_MINUTES = 15
    JWT_TYP = "jwt"
    JWT_KID = "auth-key-v1"
    REFRESH_TOKEN_EXPIRE_IN_MINUTES = 30
