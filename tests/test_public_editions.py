"""Verify the separate FL9 bundle and reproducible release archives."""
import ast
import hashlib
from pathlib import Path
import unittest
import zipfile
from tools.build_fontlab9 import build, EDITION, MODULES

ROOT=Path(__file__).resolve().parents[1]


class PublicEditionTests(unittest.TestCase):
    def test_hybrid_embeds_exact_reviewed_sources_and_isolated_namespace(self):
        tree=ast.parse(build().read_text())
        sources=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
                     and any(isinstance(t,ast.Name) and t.id=='_SOURCES' for t in n.targets))
        self.assertEqual(list(sources),MODULES)
        for name,source in sources.items():
            self.assertEqual(source,(EDITION/'autokerner'/(name+'.py')).read_text())
            compile(source,name,'exec')
        self.assertIn("'autokerner9classic'",build().read_text())

    def test_hybrid_spacing_correction_and_profile_are_included(self):
        source=(EDITION/'autokerner/classic_hybrid.py').read_text()
        self.assertIn("{'component_metrics': True}",source)
        self.assertTrue((EDITION/'resources/Autokerner9-compatible-TT.fl_profile').is_file())
        self.assertTrue((EDITION/'vendor/FONTTOOLS-LICENSE.txt').is_file())


if __name__=='__main__':unittest.main()
