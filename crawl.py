import json
import logging
import os
import shutil

import dateutil.parser
import requests

logger = logging.getLogger(__name__)

storage_dir = 'storage'
meta_dir = f'{storage_dir}/.meta'
repo_id_key = 'slug'
doc_id_key = 'slug'


class Cache:
    def __init__(self, meta_dir: str) -> None:
        self.meta_dir = meta_dir

    def request(self, api: str, cache_name=None):
        cache_path = f'{self.meta_dir}/{cache_name or api}.json'
        if os.path.exists(cache_path):
            with open(cache_path, 'rt', encoding='utf-8') as f:
                return json.load(f)
    
    def get_user(self, user=''):
        return self.request('user')
    
    def get_repos(self, user: str):
        return self.request(f'{user}/repos')
    
    def get_repo_detail(self, namespace: str):
        return self.request(f'{namespace}/repo')
    
    def get_docs(self, namespace: str):
        return self.request(f'{namespace}/docs')
    
    def get_doc_detail(self, namespace: str, name: str):
        return self.request(f'{namespace}/docs/{name}')
    
    def get_local_repo_names(self, user: str):
        dir = f'{self.meta_dir}/{user}'
        names = sorted(os.listdir(dir))
        names = [x for x in names if os.path.isdir(f'{dir}/{x}')]
        return names
    
    def get_doc_names(self, namespace: str):
        dir = f'{self.meta_dir}/{namespace}/docs'
        names = sorted(os.listdir(dir)) if os.path.exists(dir) else []
        names = [x[:-5] for x in names if x.endswith('.json')]
        return names


class SDK:
    """https://www.yuque.com/yuque/developer/api
    """
    def __init__(self, token: str, host=None, user_agent=None) -> None:
        self.token = token
        self.host = host or 'https://www.yuque.com'
        self.user_agent = user_agent or 'yuque-sdk'
        assert token

    def request(self, api: str):
        headers = {
            'User-Agent': self.user_agent,
            'X-Auth-Token': self.token
        }
        url = f'{self.host}/api/v2/{api}'
        r = requests.get(url, headers=headers, allow_redirects=True)
        d = r.json()
        if r.status_code != 200:
            raise Exception(f'Request {url} failed: {d}')
        return d['data']
    
    def get_user(self, user=''):
        return self.request(f'users/{user}' if user else 'user')
    
    def get_repos(self, user: str):
        return self.request(f'users/{user}/repos')
    
    def get_repo_detail(self, namespace: str):
        return self.request(f'repos/{namespace}')
    
    def get_docs(self, namespace: str):
        return self.request(f'repos/{namespace}/docs')
    
    def get_doc_detail(self, namespace: str, name: str):
        """https://www.yuque.com/yuque/developer/docdetailserializer
            - body: 正文 Markdown 源代码
            - body_draft: 草稿 Markdown 源代码
            - body_html: 转换过后的正文 HTML （重大变更，详情请参考：https://www.yuque.com/yuque/developer/yr938f）
        """
        return self.request(f'repos/{namespace}/docs/{name}')


def save_to_storage(filepath: str, content: str | bytes | dict):
    path = os.path.join(meta_dir, filepath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(content, str):
        with open(path, 'wt', encoding='utf-8') as f:
            f.write(content)
    elif isinstance(content, bytes):
        with open(path, 'wb') as f:
            f.write(content)
    else:
        with open(path, 'wt', encoding='utf-8') as f:
            json.dump(content, f, indent=2)


def crawl_repo(cache: Cache, sdk: SDK, namespace: str):
    cached_repo = cache.get_repo_detail(namespace)
    repo = sdk.get_repo_detail(namespace)
    if cached_repo is not None:
        if not has_update(cached_repo, repo):
            return

    docs = sdk.get_docs(namespace)

    # Remove old docs
    doc_names = [x[doc_id_key] for x in docs]
    for doc_name in cache.get_doc_names(namespace):
        if doc_name not in doc_names:
            path = f'{meta_dir}/{namespace}/{doc_name}.json'
            if os.path.exists(path):
                logger.warning(f'  {namespace}/{doc_name}.json [removed]')
                os.remove(path)

    # Crawl new docs
    cached_docs = cache.get_docs(namespace)
    for i, doc in enumerate(docs):
        if cached_docs is not None:
            cached_doc_candidates = [x for x in cached_docs if x[doc_id_key] == doc[doc_id_key]]
            if cached_doc_candidates:
                cached_doc = cached_doc_candidates[0]
                if not has_update(cached_doc, doc):
                    logger.info(f'  {doc["title"]} [no update] ({i+1}/{len(docs)})')
                    continue
        logger.info(f'  {doc["title"]} ({i+1}/{len(docs)})')
        name = doc[doc_id_key]
        doc_detail = sdk.get_doc_detail(namespace, name)
        save_to_storage(f'{namespace}/docs/{name}.json', doc_detail)

    save_to_storage(f'{namespace}/docs.json', docs)
    save_to_storage(f'{namespace}/toc.yaml', repo['toc_yml'])
    save_to_storage(f'{namespace}/repo.json', repo)


def has_update(cached_d, d, key='updated_at'):
    old_updated_at = dateutil.parser.parse(cached_d[key])
    updated_at = dateutil.parser.parse(d[key])
    diff = updated_at - old_updated_at
    return diff.seconds > 0


def setup_logging(logger, log_file='main.log'):
    # 创建一个文件处理器，将日志写入到文件中
    file_handler = logging.FileHandler(log_file, mode='w')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)-.4s - %(message)s"))
    logger.addHandler(file_handler)

    # 创建一个控制台处理器，将日志输出到控制台
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(levelname)-.4s - %(message)s"))
    logger.addHandler(console_handler)


def load_token(config_path = 'config.json'):
    import json
    token = json.load(open('config.json', encoding="utf-8")).get('token')
    return token


def main():
    logger.setLevel(logging.DEBUG)
    os.makedirs(meta_dir, exist_ok=True)
    setup_logging(logger, f'{meta_dir}/main.log')

    sdk = SDK(load_token())
    cache = Cache(meta_dir)

    cached_user_info = cache.get_user()
    user_info = sdk.get_user()
    user_info_updated = True
    if cached_user_info is not None:
        if not has_update(cached_user_info, user_info):
            user_info_updated = False
    if user_info_updated:
        save_to_storage(f'user.json', user_info)

    login = user_info['login']
    repos = sdk.get_repos(login)

    # Remove old repos
    repo_names = [x[repo_id_key] for x in repos]
    for repo_name in cache.get_local_repo_names(login):
        if repo_name not in repo_names:
            logger.warning(f'Remove repo {login}/{repo_name}')
            shutil.rmtree(f'{meta_dir}/{login}/{repo_name}')
    
    # Crawling new repos
    cached_repos = cache.get_repos(login)
    for i, repo in enumerate(repos):
        logger.info(f'Crawling repo {repo["name"]} ({i+1}/{len(repos)})')
        if cached_repos is not None:
            cached_repo_candidates = [x for x in cached_repos if x[repo_id_key] == repo[repo_id_key]]
            if cached_repo_candidates:
                cached_repo = cached_repo_candidates[0]
                if not has_update(cached_repo, repo):
                    logger.warning(f'  No update')
                    continue
        crawl_repo(cache, sdk, repo['namespace'])

    save_to_storage(f'{login}/repos.json', repos)


if __name__ == '__main__':
    main()