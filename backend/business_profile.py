"""Business classifications; no inference of passenger/cargo use from a model code."""
VESSEL_TYPES={'container':'集装箱船','tanker':'油轮','liquid_cargo':'液货船（细分未提供）','bulk':'散货船','cargo':'货船（细分未提供）',
              'passenger':'客船','pilot':'引航船','tug':'拖轮','fishing':'渔船','other':'其他船舶'}
AIRCRAFT_ROLES={'passenger':'客机','cargo':'货机','mixed':'客货混合','other':'其他用途'}


def describe_profile(monitor):
    manual=monitor['profile'];data=(monitor.get('latest') or {}).get('data',{})
    kind=monitor['kind']
    if monitor.get('source',{}).get('profile_mode')=='provider':
        category=data.get('aircraft_category') if kind!='vessel' else data.get('vessel_type')
        model=data.get('aircraft_type')
        return {'category':category,'category_label':category or '分类未提供',
                'aircraft_model':model,'category_source':'provider' if category else None,
                'model_source':'provider' if model else None}
    category_field='vessel_type' if kind=='vessel' else 'aircraft_role'
    category=manual.get(category_field) or data.get(category_field)
    labels=VESSEL_TYPES if kind=='vessel' else AIRCRAFT_ROLES
    model=manual.get('aircraft_model') or data.get('aircraft_type')
    return {'category':category,'category_label':labels.get(category,'未分类'),
            'aircraft_model':model,'category_source':'manual' if manual.get(category_field) else 'provider' if category else None,
            'model_source':'manual' if manual.get('aircraft_model') else 'provider' if model else None}
