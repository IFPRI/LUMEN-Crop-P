"""Small helpers around gams.transfer so the pipeline steps read and write GDX the same way."""
import pandas as pd
import gams.transfer as gt


class PipelineError(RuntimeError):
    """A check failed. The message says which one; the driver stops the run."""


def open_gdx(path, gamsdir):
    return gt.Container(load_from=str(path), system_directory=str(gamsdir))


def new_gdx(gamsdir):
    return gt.Container(system_directory=str(gamsdir))


def records(sym, names):
    """Records of a symbol as a plain DataFrame: first len(names) columns, categoricals as str.

    Works for Sets (domain columns + element_text) and Parameters (domain columns + value)
    alike, because only the leading columns are taken.
    """
    r = sym.records
    if r is None or len(r) == 0:
        return pd.DataFrame({n: pd.Series(dtype=object) for n in names})
    r = r.iloc[:, : len(names)].copy()
    r.columns = names
    for c in names:
        if isinstance(r[c].dtype, pd.CategoricalDtype):
            r[c] = r[c].astype(str)
    return r.reset_index(drop=True)


def param3(c, name, cols):
    """3-dim parameter -> DataFrame with columns cols (3 keys) + 'value'."""
    return records(c[name], list(cols) + ["value"])


def param1(c, name, key):
    return records(c[name], [key, "value"])


def set1(c, name):
    return set(records(c[name], ["k"]).k)


def long_coords(df, key):
    """(key, x, y) wide -> (key, coord, value) long, ordered key then x,y."""
    out = df[[key, "x", "y"]].melt(id_vars=key, var_name="coord", value_name="value")
    out["coord"] = pd.Categorical(out["coord"], categories=["x", "y"])
    return out.sort_values([key, "coord"], kind="stable").reset_index(drop=True)
