"""Offline privacy, boundedness, missing-data and cross-period facet contracts."""
import copy
import hashlib
import json
import unittest

import search_demand as d

PERIOD = dict(startDate='2026-10-23', endDate='2026-11-19', dateBasis='America/Los_Angeles')


def row(query, impressions=100, clicks=10, position=10):
    return dict(query=query, impressions=impressions, clicks=clicks, position=position, ctr=.999)


class SearchDemandTests(unittest.TestCase):
    def test_controlled_winter_apparel_brands_and_comparison(self):
        cases = [('モンベル パタゴニア 冬 ダウン 比較', 'down'),
                 ('THE NORTH FACE 秋 フリース おすすめ', 'fleece'),
                 ('ファイントラック 冬 アクティブインサレーション 違い', 'active_insulation'),
                 ('Icebreaker Smartwool ベースレイヤー vs', 'base_layer'),
                 ("ARC’TERYX ハードシェル 冬", 'hard_shell'),
                 ('MAMMUT softshell winter jacket', 'soft_shell')]
        for text, garment in cases:
            f = d.classify_topic(text)
            with self.subTest(garment=garment):
                self.assertIn(garment, f['garments']); self.assertIn('apparel', f['gearTypes'])
                self.assertEqual(set(d.FACET_KEYS), set(f))
                for key, values in f.items():
                    self.assertEqual(values, sorted(set(values)))
                    self.assertTrue(set(values) <= set(d.ALIASES[key]))
        self.assertEqual(['montbell','patagonia'], d.classify_topic(cases[0][0])['brands'])
        self.assertEqual(['comparison'], d.classify_topic(cases[0][0])['intents'])
        self.assertEqual(['arcteryx'], d.classify_topic(cases[4][0])['brands'])

    def test_no_inferred_season_brand_or_garment_from_unrelated_text(self):
        self.assertEqual([], d.classify_topic('ダウン 比較')['seasons'])
        self.assertEqual([], d.classify_topic('冬 ダウン寝袋 比較')['garments'])
        self.assertEqual(['sleeping_bag'], d.classify_topic('冬 ダウン寝袋 比較')['gearTypes'])
        self.assertEqual([], d.classify_topic('テントのトラブル isotope rabid MSRX')['brands'])
        self.assertEqual(['rab'], d.classify_topic('ラブ ダウン')['brands'])
        self.assertEqual({key: [] for key in d.FACET_KEYS}, d.classify_topic(None))
        self.assertEqual([], d.classify_topic('モンベル パタゴニア')['intents'])
        f = d.classify_topic('サーモス 水筒 品番 パッキン 探す')
        self.assertEqual(['thermos'], f['brands']); self.assertEqual(['bottle'], f['gearTypes'])
        self.assertEqual(['compatibility'], f['problems'])

    def test_owner_apparel_aliases_and_known_families_without_performance_inference(self):
        for text in ('冬 インナー 比較', 'ジオライン 比較'):
            facets=d.classify_topic(text)
            self.assertIn('base_layer',facets['garments']);self.assertIn('apparel',facets['gearTypes'])
        self.assertIn('fleece',d.classify_topic('シャミース 比較')['garments'])
        self.assertEqual([],d.classify_topic('ジオライン シャミース 比較')['problems'])
        self.assertEqual([],d.classify_topic('ジオライン シャミース 比較')['seasons'])
        for text in ('インナーテント', 'インナー テント', 'インナー・テント', 'インナーダウン', 'インナー ダウン'):
            with self.subTest(text=text):self.assertNotIn('base_layer',d.classify_topic(text)['garments'])
        self.assertEqual(['down'],d.classify_topic('インナーダウン')['garments'])
        self.assertEqual(['base_layer','down'],d.classify_topic('インナーダウンとジオラインを比較')['garments'])
        self.assertEqual(['base_layer','down'],d.classify_topic('インナーダウンとインナーを比較')['garments'])
        for brand in ('ザ・ノース・フェイス','thenorthface','ＴＨＥＮＯＲＴＨＦＡＣＥ'):
            with self.subTest(brand=brand):self.assertEqual(['the_north_face'],d.classify_topic(brand)['brands'])

    def test_layering_and_moisture_problem_facets_are_controlled_query_topics(self):
        for text in ('レイヤリング','重ね着','layering'):
            f=d.classify_topic(text);self.assertEqual(['layering'],f['problems']);self.assertIn('apparel',f['gearTypes'])
        for text,problem in [('蒸れ','moisture'),('ムレ','moisture'),('汗冷え','sweat_cold'),
                             ('透湿','breathability'),('速乾','quick_dry')]:
            with self.subTest(text=text):self.assertEqual([problem],d.classify_topic(text)['problems'])
        query='ザ・ノース・フェイス 冬 インナー 重ね着 蒸れ 汗冷え 透湿 速乾 private-sentinel'
        group=d.project_search_demand([row(query)],PERIOD)['groups'][0]
        self.assertEqual(['breathability','layering','moisture','quick_dry','sweat_cold'],group['facets']['problems'])
        self.assertNotIn('private-sentinel',json.dumps(group))

    def test_aggregate_dedup_counts_ctr_and_impression_weighted_position(self):
        rows = [row('モンベル 冬 ダウン 比較 private-a',100,10,10),
                row('モンベル 冬 ダウン 比較 private-b',300,30,30)]
        rows += [copy.deepcopy(rows[0])]
        out = d.project_search_demand(rows, PERIOD)
        group = out['groups'][0]
        self.assertEqual(2, group['queryCount'])
        self.assertEqual(dict(clicks=40,impressions=400,ctr=.1,averagePosition=25), group['metrics'])
        self.assertEqual(1,out['coverage']['duplicateRowCount'])
        self.assertFalse(out['coverage']['marketDemand']); self.assertFalse(out['coverage']['trendVerified'])
        self.assertEqual('impression_weighted',out['coverage']['positionAggregation'])

    def test_conflicting_duplicate_keeps_one_whole_row_and_is_order_independent(self):
        rows = [row('ＭＯＮＴＢＥＬＬ  冬 フリース',100,10,5),
                row('ＭＯＮＴＢＥＬＬ  冬 フリース',200,None,20),
                row('ＭＯＮＴＢＥＬＬ  冬 フリース',100,10,5)]
        before=copy.deepcopy(rows); out=d.project_search_demand(rows,PERIOD)
        self.assertEqual(out,d.project_search_demand(list(reversed(rows)),PERIOD));self.assertEqual(before,rows)
        self.assertEqual(1,out['groups'][0]['queryCount']);self.assertEqual(200,out['groups'][0]['metrics']['impressions'])
        self.assertIsNone(out['groups'][0]['metrics']['clicks']);self.assertIsNone(out['groups'][0]['metrics']['ctr'])
        self.assertEqual(20,out['groups'][0]['metrics']['averagePosition'])
        self.assertEqual(1,out['coverage']['conflictingDuplicateCount']);self.assertFalse(out['coverage']['observedRowsComplete'])

    def test_distinct_gsc_query_spellings_group_without_losing_measured_counts(self):
        out=d.project_search_demand([row('ＭＯＮＴＢＥＬＬ 冬 フリース'),row('montbell 冬 フリース')],PERIOD)
        self.assertEqual(1,len(out['groups']));self.assertEqual(2,out['groups'][0]['queryCount'])
        self.assertEqual(200,out['groups'][0]['metrics']['impressions']);self.assertEqual(0,out['coverage']['duplicateRowCount'])

    def test_missing_zero_and_invalid_metrics_are_distinct(self):
        self.assertEqual('unavailable',d.project_search_demand(None,PERIOD)['status'])
        self.assertIsNone(d.project_search_demand(None,PERIOD)['coverage']['uniqueQueryCount'])
        empty=d.project_search_demand([],PERIOD)
        self.assertEqual('available',empty['status']);self.assertEqual(0,empty['coverage']['uniqueQueryCount'])
        out=d.project_search_demand([row('冬 フリース a',100,0,None),row('冬 フリース b',100,None,10)],PERIOD)
        self.assertEqual(200,out['groups'][0]['metrics']['impressions'])
        for key in ('clicks','ctr','averagePosition'):self.assertIsNone(out['groups'][0]['metrics'][key])
        zero=d.project_search_demand([row('冬 フリース',100,0,10)],PERIOD)['groups'][0]['metrics']
        self.assertEqual(0,zero['clicks']);self.assertEqual(0,zero['ctr'])
        no_impressions=d.project_search_demand([row('冬 フリース',0,0,None)],PERIOD)['groups'][0]['metrics']
        self.assertEqual(0,no_impressions['impressions']);self.assertIsNone(no_impressions['ctr']);self.assertIsNone(no_impressions['averagePosition'])
        for invalid in (True,-1,float('nan'),float('inf'),'secret',1.5):
            with self.subTest(invalid=invalid):
                metrics=d.project_search_demand([row('冬 フリース',invalid,0,10)],PERIOD)['groups'][0]['metrics']
                self.assertIsNone(metrics['impressions']);self.assertIsNone(metrics['averagePosition'])
        json.dumps(out,allow_nan=False)

    def test_facet_identity_shared_across_periods_without_absence_zero_fill(self):
        a=d.project_search_demand([row('冬 モンベル フリース')],PERIOD)
        old=dict(PERIOD,startDate='2026-09-25',endDate='2026-10-22')
        b=d.project_search_demand([row('冬 モンベル フリース',200,20,20)],old)
        self.assertEqual(a['groups'][0]['facetId'],b['groups'][0]['facetId'])
        self.assertNotEqual(a['groups'][0]['id'],b['groups'][0]['id'])
        self.assertEqual([],d.project_search_demand([],old)['groups'])
        self.assertEqual('unavailable',d.project_search_demand([row('冬')],dict(PERIOD,endDate='bad'))['status'])
        self.assertEqual('unavailable',d.project_search_demand([],dict(PERIOD,dateBasis='secret-zone'))['status'])

    def test_privacy_no_raw_strings_hashes_uncontrolled_labels_or_extra_period_fields(self):
        term='モンベル 冬 ダウン 比較 personal@example.invalid secret-token-9901'
        period=dict(PERIOD,private='do-not-export')
        out=d.project_search_demand([row(term)],period);text=json.dumps(out,ensure_ascii=False)
        for forbidden in (term,'personal@','secret-token','do-not-export',hashlib.sha256(term.encode()).hexdigest()):
            self.assertNotIn(forbidden,text)
        f=out['groups'][0]['facets'];self.assertEqual(d._hash(f),out['groups'][0]['facetId'])
        self.assertEqual(PERIOD,out['period'])
        expected='gsc-demand:'+d._hash(dict(facets=f,period=PERIOD))
        self.assertEqual(expected,out['groups'][0]['id'])

    def test_processed_row_and_group_caps_and_unclassified_coverage(self):
        rows=[row(f'{brand} {season} {problem}') for brand in ('montbell','patagonia','mammut','coleman')
              for season in ('winter','summer','autumn','spring') for problem in ('cold','rain','wind')]
        out=d.project_search_demand(rows,PERIOD)
        self.assertEqual(40,len(out['groups']));self.assertTrue(out['coverage']['groupsTruncated'])
        self.assertEqual(48,out['coverage']['observedGroupCount'])
        self.assertEqual(out,d.project_search_demand(list(reversed(rows)),PERIOD))
        capped=d.project_search_demand([row('冬')]*10001,PERIOD)
        self.assertEqual(10000,capped['coverage']['processedRowCount']);self.assertTrue(capped['coverage']['inputTruncated'])
        self.assertEqual(1,capped['groups'][0]['queryCount']);self.assertEqual(100,capped['groups'][0]['metrics']['impressions'])
        mixed=d.project_search_demand([None,{'query':' '},row('unclassified-private'),row('冬')],PERIOD)
        self.assertEqual(2,mixed['coverage']['invalidRowCount']);self.assertEqual(1,mixed['coverage']['unclassifiedQueryCount'])
        self.assertEqual(1,mixed['coverage']['classifiedQueryCount'])
    def test_many_strong_seasonal_groups_do_not_crowd_out_tail_apparel_or_comparison(self):
        rows=[row(f'{brand} {season} {problem}',1000-i,10,8)
              for i,(brand,season,problem) in enumerate((b,s,p)
              for b in ('montbell','patagonia','mammut','coleman')
              for s in ('winter','summer','autumn','spring') for p in ('cold','rain','wind'))]
        rows += [row('冬 フリース private-apparel-tail',1,0,5),
                 row('モンベル パタゴニア テント 比較 private-comparison-tail',2,0,8)]
        before=copy.deepcopy(rows);out=d.project_search_demand(rows,PERIOD)
        self.assertEqual(before,rows);self.assertEqual(out,d.project_search_demand(list(reversed(rows)),PERIOD))
        self.assertEqual(40,len(out['groups']));self.assertEqual(40,len({g['id'] for g in out['groups']}))
        self.assertTrue(out['coverage']['groupsTruncated']);self.assertEqual(50,out['coverage']['observedGroupCount'])
        apparel=[g for g in out['groups'] if g['facets']['garments']]
        comparison=[g for g in out['groups'] if len(g['facets']['brands'])>=2 and 'comparison' in g['facets']['intents']]
        self.assertEqual(1,len(apparel));self.assertEqual(1,apparel[0]['metrics']['impressions']);self.assertEqual(0,apparel[0]['metrics']['clicks'])
        self.assertEqual(1,len(comparison));self.assertEqual(2,comparison[0]['metrics']['impressions'])
        coverage=out['coverage']
        self.assertEqual('preferred_context_round_robin_then_global_v1',coverage['selectionPolicy'])
        self.assertEqual(20,coverage['preferredGroupCount']);self.assertEqual(20,coverage['globalFillGroupCount'])
        self.assertEqual(1,coverage['observedApparelGroupCount']);self.assertEqual(1,coverage['exportedApparelGroupCount'])
        self.assertEqual(1,coverage['observedBrandComparisonGroupCount']);self.assertEqual(1,coverage['exportedBrandComparisonGroupCount'])
        self.assertEqual(49,coverage['observedSeasonalGroupCount'])
        full=self._all_observed_groups(rows)
        for group in out['groups']:self.assertEqual(full[group['id']],group)
        preferred=out['groups'][:coverage['preferredGroupCount']];global_fill=out['groups'][coverage['preferredGroupCount']:]
        self.assertEqual(preferred,sorted(preferred,key=self._strength))
        self.assertEqual(global_fill,sorted(global_fill,key=self._strength))
        wanted=sorted([g for g in full.values() if g['id'] not in {p['id'] for p in preferred}],key=self._strength)[:20]
        self.assertEqual(wanted,global_fill)
        for term in ('private-apparel-tail','private-comparison-tail'):self.assertNotIn(term,json.dumps(out))

    @staticmethod
    def _strength(group):
        return (-group['metrics']['impressions'],-group['metrics']['clicks'],group['facetId'])

    @staticmethod
    def _all_observed_groups(rows):
        # One-row projections reconstruct observed groups without defeating the export cap.
        return {g['id']:g for source in rows for g in d.project_search_demand([source],PERIOD)['groups']}

    def test_scarce_or_no_preferred_groups_fill_all_available_slots_from_global_strength(self):
        rows=[row(f'{brand} {gear} {problem}',500-i,5,8)
              for i,(brand,gear,problem) in enumerate((b,g,p)
              for b in ('montbell','patagonia','mammut','coleman')
              for g in ('tent','stove','chair','bottle') for p in ('cold','rain','wind'))]
        no_preferred=d.project_search_demand(rows,PERIOD)
        self.assertEqual(0,no_preferred['coverage']['preferredGroupCount'])
        self.assertEqual(40,no_preferred['coverage']['globalFillGroupCount'])
        self.assertEqual(sorted(self._all_observed_groups(rows).values(),key=self._strength)[:40],no_preferred['groups'])
        scarce=d.project_search_demand(rows+[row('冬 フリース',1,0,5)],PERIOD)
        self.assertEqual(1,scarce['coverage']['preferredGroupCount']);self.assertEqual(39,scarce['coverage']['globalFillGroupCount'])
        self.assertEqual(40,len(scarce['groups']));self.assertTrue(scarce['groups'][0]['facets']['garments'])
        small=d.project_search_demand(rows[:5],PERIOD)
        self.assertEqual(5,len(small['groups']));self.assertFalse(small['coverage']['groupsTruncated'])

    def test_preferred_overlap_is_deduplicated_and_limited_to_twenty_with_remaining_global_fill(self):
        rows=[row(f'{brand} 冬 フリース 比較 {problem}',100-i,5,8)
              for i,(brand,problem) in enumerate((b,p) for b in ('montbell','patagonia','mammut','coleman','uniqlo','workman')
              for p in ('cold','rain','wind','washing'))]
        out=d.project_search_demand(rows,PERIOD)
        self.assertEqual(24,len(out['groups']));self.assertEqual(24,len({g['facetId'] for g in out['groups']}))
        self.assertEqual(20,out['coverage']['preferredGroupCount']);self.assertEqual(4,out['coverage']['globalFillGroupCount'])
        self.assertEqual(24,out['coverage']['exportedApparelGroupCount']);self.assertEqual(24,out['coverage']['exportedSeasonalGroupCount'])
        self.assertEqual([],d.project_search_demand([],PERIOD)['groups'])
        missing=d.project_search_demand(None,PERIOD)['coverage']
        self.assertIsNone(missing['preferredGroupCount']);self.assertIsNone(missing['exportedApparelGroupCount'])


if __name__=='__main__':
    unittest.main()
