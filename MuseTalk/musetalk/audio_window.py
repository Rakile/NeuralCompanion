"""Select visible conditioning frames while retaining full audio encoder context."""


def select_render_features(features, *, skip=0, maximum=None):
    if type(skip) is not int or skip < 0:
        raise ValueError('Audio context prefix must be a nonnegative integer')
    if skip and skip >= len(features):
        raise ValueError('Audio context prefix leaves no visible speech frames')
    if maximum is None:
        return features[skip:] if skip else features
    maximum = max(1, int(maximum))
    return features[skip:skip + maximum]
