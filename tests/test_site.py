"""Static site: links, escaping, no-JavaScript usability, determinism."""

import json
import re
from collections import deque
from pathlib import Path

from bibgraph import checks, model, site, util

from .support import WorkspaceCase


class SiteCase(WorkspaceCase):
    def build(self, public=False, profile=None):
        if profile is not None:
            util.write_json_atomic(self.ws.profile_file, {
                "schema_version": "1.0", "name": "t", "selections": profile})
        corpus, deps, prof, _issues = checks.load_and_validate(self.ws)
        data = site.load_site_data(self.ws, corpus, deps, prof, public=public)
        self.out = self.root / ("publish" if public else "build/site")
        site.build_site(self.ws, data, self.out)
        return self.out

    def read(self, relative):
        return (self.out / relative).read_text(encoding="utf-8")


class TestLinks(SiteCase):
    def test_no_broken_internal_links(self):
        report = checks.check_site(self.build())
        self.assertEqual([i for i in report["issues"] if i["severity"] == "error"], [])

    def test_every_work_is_reachable_from_the_index_within_three_clicks(self):
        root = self.build()
        corpus = model.load_corpus(self.ws.corpus_file)
        depth = {"index.html": 0}
        queue = deque(["index.html"])
        while queue:
            key = queue.popleft()
            if depth[key] >= 3:
                continue
            for target in self._internal_targets(root, key):
                if target not in depth:
                    depth[target] = depth[key] + 1
                    queue.append(target)
        for work in corpus.works:
            page = f"works/{util.safe_path_segment(work.primary_alias)}/index.html"
            self.assertIn(page, depth, f"{work.primary_alias} is unreachable")
            self.assertLessEqual(depth[page], 3, work.primary_alias)

    @staticmethod
    def _internal_targets(root, key):
        collector = checks._LinkCollector()
        collector.feed((root / key).read_text(encoding="utf-8"))
        out = []
        for _tag, link in collector.links:
            if link.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path = link.split("#", 1)[0]
            if not path:
                continue
            resolved = checks._normalize_rel((Path(key).parent / path).as_posix())
            for candidate in (resolved, resolved.rstrip("/") + "/index.html"):
                if (root / candidate).is_file() and candidate.endswith(".html"):
                    out.append(candidate)
                    break
        return out

    def test_no_link_is_root_relative(self):
        root = self.build()
        # Root-relative links break under https://owner.github.io/repository/.
        for page in root.rglob("*.html"):
            for match in re.finditer(r'(?:href|src)="([^"]+)"', page.read_text(encoding="utf-8")):
                link = match.group(1)
                if link.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                self.assertFalse(link.startswith("/"), f"{page.name}: {link}")


class TestNoJavaScriptRequired(SiteCase):
    def test_no_inline_script_blocks(self):
        root = self.build()
        for page in root.rglob("*.html"):
            text = page.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"<script(?![^>]*\bsrc=)[^>]*>\s*\S",
                                f"{page.name} has an inline script")

    def test_no_inline_event_handlers_except_the_inert_form_guard(self):
        root = self.build()
        for page in root.rglob("*.html"):
            text = page.read_text(encoding="utf-8")
            handlers = re.findall(r'\son([a-z]+)="', text)
            self.assertTrue(set(handlers) <= {"submit"},
                            f"{page.name} uses {handlers}")

    def test_navigation_is_plain_anchors(self):
        self.build()
        nav = re.search(r'<nav aria-label="Main">(.*?)</nav>',
                        self.read("index.html"), re.S).group(1)
        self.assertEqual(nav.count("<a href="), len(site.NAV))

    def test_the_review_form_is_usable_without_javascript(self):
        self.build()
        page = self.read("works/D-R0/index.html")
        # The textarea carries the record; the download button is optional.
        self.assertIn("<textarea", page)
        self.assertIn("hidden>Download JSON</button>", page)
        self.assertIn("works without it", page)

    def test_the_only_script_is_an_external_deferred_file(self):
        self.build()
        scripts = re.findall(r"<script[^>]*>", self.read("index.html"))
        self.assertEqual(len(scripts), 1)
        self.assertIn("defer", scripts[0])
        self.assertIn('src="site.js"', scripts[0])


class TestAccessibility(SiteCase):
    def test_svg_has_an_accessible_name_and_a_text_equivalent(self):
        self.build()
        page = self.read("dependencies/index.html")
        self.assertIn('role="img"', page)
        self.assertIn('aria-labelledby="dag-title dag-desc"', page)
        self.assertIn("Adjacency list", page)

    def test_edge_types_remain_distinguishable_without_colour(self):
        self.build()
        page = self.read("dependencies/index.html")
        for edge_type in model.EDGE_TYPES:
            self.assertIn(f"arrow-{edge_type}", page, edge_type)
        self.assertIn("readable without colour perception", page)

    def test_tables_use_scoped_headers(self):
        self.build()
        self.assertIn('<th scope="col">', self.read("index.html"))


class TestEscaping(SiteCase):
    def test_hostile_metadata_is_escaped_not_injected(self):
        raw = json.loads(self.ws.corpus_file.read_text(encoding="utf-8"))
        payload = '<script>alert("xss")</script>'
        raw["works"][0]["title"] = payload
        raw["works"][0]["authors"] = ['"><img src=x onerror=alert(1)>']
        util.write_json_atomic(self.ws.corpus_file, raw)
        self.build()
        page = self.read("works/D-R0/index.html")
        self.assertNotIn(payload, page)
        self.assertIn("&lt;script&gt;", page)
        # The payload survives as escaped text; what matters is that no live
        # tag was produced from it.
        self.assertNotIn("<img", page)
        self.assertNotIn("<script>alert", page)
        body_scripts = re.findall(r"<script[^>]*>", page)
        self.assertEqual(body_scripts, ['<script src="../../site.js" defer>'])

    def test_a_hostile_alias_cannot_escape_the_output_directory(self):
        with self.assertRaises(ValueError):
            util.safe_path_segment("../../etc/passwd")


class TestChoicePresentation(SiteCase):
    def test_unresolved_choice_is_shown_as_a_branch_not_a_decision(self):
        self.build(profile={"choice:demo-text": None})
        page = self.read("dependencies/index.html")
        self.assertIn("will not choose one on your behalf", page)
        self.assertIn("unresolved", page)
        for arm in ("D-A2", "D-A3"):
            self.assertIn(arm, page)

    def test_an_arm_page_links_to_its_alternative(self):
        self.build()
        page = self.read("works/D-A2/index.html")
        self.assertIn("Alternative.", page)
        self.assertIn("D-A3", page)
        self.assertIn("Neither has been selected.", page)

    def test_selecting_an_arm_is_reflected_on_the_page(self):
        self.build(profile={"choice:demo-text": "D-A2"})
        page = self.read("dependencies/index.html")
        self.assertIn("selected", page)


class TestIncompleteness(SiteCase):
    def test_an_unextracted_work_shows_a_reason_not_an_empty_field(self):
        self.build()
        page = self.read("works/D-R0/index.html")
        self.assertIn("Not extracted yet", page)
        self.assertIn("never be displayed as an empty success", page)

    def test_placeholder_corpus_carries_a_visible_notice(self):
        raw = json.loads(self.ws.corpus_file.read_text(encoding="utf-8"))
        raw["source"]["supplied"] = False
        util.write_json_atomic(self.ws.corpus_file, raw)
        self.build()
        self.assertIn("Incomplete corpus", self.read("index.html"))

    def test_an_empty_dag_is_reported_rather_than_drawn(self):
        raw = json.loads(self.ws.dependencies_file.read_text(encoding="utf-8"))
        raw["edges"] = []
        util.write_json_atomic(self.ws.dependencies_file, raw)
        self.build()
        page = self.read("dependencies/index.html")
        self.assertIn("No dependency edge has been recorded", page)
        self.assertNotIn("<svg", page)


class TestDeterminism(SiteCase):
    def test_two_builds_of_unchanged_inputs_are_identical(self):
        import os

        os.environ["SOURCE_DATE_EPOCH"] = "1758000000"
        self.addCleanup(os.environ.pop, "SOURCE_DATE_EPOCH", None)
        first = {p.name: p.read_bytes() for p in self.build().rglob("*") if p.is_file()}
        second = {p.name: p.read_bytes() for p in self.build().rglob("*") if p.is_file()}
        self.assertEqual(first, second)


class TestSubpathHosting(SiteCase):
    def test_pages_resolve_under_a_repository_subpath(self):
        root = self.build()
        # Simulate https://owner.github.io/repo/ by nesting the build.
        nested = self.root / "gh" / "repo"
        nested.parent.mkdir(parents=True, exist_ok=True)
        root.rename(nested)
        self.out = nested
        report = checks.check_site(nested)
        self.assertEqual(report["errors"], 0)
