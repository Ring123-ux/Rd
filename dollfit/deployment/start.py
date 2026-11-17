import os
from .assets import restore


def main():
    restore()
    import uvicorn
    uvicorn.run('runtime.cloud_app:app', host='0.0.0.0', port=int(os.environ.get('PORT', '10000')),
                workers=1, proxy_headers=True, forwarded_allow_ips='*', timeout_keep_alive=10)


if __name__ == '__main__':
    main()
