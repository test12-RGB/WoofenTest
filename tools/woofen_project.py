"""把 Issue 的 BUG等级/状态/信息 维护到组织看板（GitHub Projects v2 自定义字段）。

标签只表达归属，等级/状态/信息在看板字段里展示，Issue 侧边栏可见。
"""
import json
import subprocess

PROJECT_ID = "PVT_kwDOEjM3M84BsHpL"
FIELD_LEVEL = "PVTSSF_lADOEjM3M84BsHpLzhqXNno"
FIELD_STATE = "PVTSSF_lADOEjM3M84BsHpLzhqXNoU"
FIELD_INFO = "PVTSSF_lADOEjM3M84BsHpLzhqXNoc"

LEVEL_OPTS = {"P0": "3c26e9cb", "P1": "f17d7742", "P2": "9bdc29be", "P3": "9e1073f2"}
STATE_OPTS = {"开放": "85ee8851", "已解决": "dde7a207", "关闭": "46a358d2"}
INFO_OPTS = {"非问题": "2ce8448b", "重复问题": "7f284fcc", "无法解决": "681a270e"}


def gql(query):
    r = subprocess.run(["gh", "api", "graphql", "-f", "query=" + query],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300])
    d = json.loads(r.stdout)
    if "errors" in d:
        raise RuntimeError(str(d["errors"])[:300])
    return d["data"]


def _alias(i):
    return "a%d" % i


def add_items(node_ids):
    """把 Issue 加进看板，返回 {node_id: item_id}"""
    out = {}
    for chunk in [node_ids[i:i + 8] for i in range(0, len(node_ids), 8)]:
        body = " ".join(
            '%s:addProjectV2ItemById(input:{projectId:"%s",contentId:"%s"}){item{id}}'
            % (_alias(i), PROJECT_ID, nid) for i, nid in enumerate(chunk))
        data = gql("mutation{" + body + "}")
        for i, nid in enumerate(chunk):
            out[nid] = data[_alias(i)]["item"]["id"]
    return out


def _field_parts(prefix, item_id, level, status, info, counter=[0]):
    parts = []
    for fld, val, opts in ((FIELD_LEVEL, level, LEVEL_OPTS),
                           (FIELD_STATE, status, STATE_OPTS),
                           (FIELD_INFO, info, INFO_OPTS)):
        if val and val in opts:
            parts.append(
                '%s%d:updateProjectV2ItemFieldValue(input:{projectId:"%s",itemId:"%s",'
                'fieldId:"%s",value:{singleSelectOptionId:"%s"}}){clientMutationId}'
                % (prefix, counter[0], PROJECT_ID, item_id, fld, opts[val]))
            counter[0] += 1
    return parts


def set_fields(item_id, level, status, info):
    parts = _field_parts("s", item_id, level, status, info)
    if parts:
        gql("mutation{" + " ".join(parts) + "}")


def batch_set(items):
    """items: [(item_id, level, status, info)]"""
    for chunk in [items[i:i + 6] for i in range(0, len(items), 6)]:
        parts = []
        for item_id, level, status, info in chunk:
            parts += _field_parts("b", item_id, level, status, info)
        if parts:
            gql("mutation{" + " ".join(parts) + "}")


def list_items():
    """返回 {issue_number: item_id}"""
    out = {}
    cursor = None
    while True:
        after = 'after:"%s",' % cursor if cursor else ""
        q = ('query{organization(login:"brainvue-tech"){projectV2(number:3){items(first:100,%s){'
             'pageInfo{hasNextPage endCursor} nodes{id content{... on Issue{number}}}}}}}') % after
        d = gql(q)["organization"]["projectV2"]["items"]
        for n in d["nodes"]:
            c = n.get("content") or {}
            if c.get("number"):
                out[c["number"]] = n["id"]
        if not d["pageInfo"]["hasNextPage"]:
            break
        cursor = d["pageInfo"]["endCursor"]
    return out
