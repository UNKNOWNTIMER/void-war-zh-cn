"""Run synthetic installer tests and save a privacy-safe acceptance summary."""
import argparse,datetime,json,pathlib,sys,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from payload_format import sha
class Result(unittest.TextTestResult):
    def __init__(self,*args,**kw):
        super().__init__(*args,**kw);self.cases=[];self.subcases=0
    def addSuccess(self,test):
        super().addSuccess(test);self.cases.append(test.id())
    def addSubTest(self,test,subtest,error):
        super().addSubTest(test,subtest,error);self.subcases+=1
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--report',type=pathlib.Path,required=True);a=ap.parse_args()
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_*.py')
    result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(suite)
    report={'status':'PASS' if result.wasSuccessful() else 'FAIL',
            'verified_at':datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
            'scope':'Synthetic temporary game directories and synthetic saves only; source-level tests, not frozen EXE or real-game acceptance.',
            'tests_run':result.testsRun,'tests_passed':len(result.cases),'fault_subcases':result.subcases,
            'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
            'passed_tests':result.cases,'python_version':sys.version.split()[0],
            'source_sha256':{name:sha(ROOT/name) for name in ['patcher_core.py','payload_format.py','installer_gui.py','tests/test_installer.py']},
            'coverage':['install/restore preserves subsequent progress','reinstall and supported upgrade','preexisting font/license restore',
                        'wrong version and missing resource preflight','corrupt delta and text payload','duplicate and invalid language field',
                        'game running guard','missing and damaged backup','17 per-write and commit failure rollback cases',
                        'restore failure rollback','hard child-process exit and next-run recovery','external profile change blocks recovery',
                        'different account profile cannot claim transaction even with identical bytes','profile change between preparation and commit',
                        'legacy PowerShell backup adoption','Chinese, spaces, brackets, ampersand and apostrophe paths',
                        'native nested savedSettings.currLanguage and preserved terminal NUL'],
            'real_installed_game_modified':False,'real_save_files_accessed':False,
            'limitations':['Final frozen EXE payload and GUI installation require separate acceptance.','No clean Windows VM or code-signing validation.']}
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:x for k,x in report.items() if k not in ['passed_tests','coverage','source_sha256']},ensure_ascii=False,indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
if __name__=='__main__':main()
