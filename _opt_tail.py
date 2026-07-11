        margin=dict(l=40, r=20, t=20, b=50),
        legend=dict(font=dict(color="#94A3B8", size=10), bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(title="Annual Volatility (Risk)", tickformat=".0%",
                   gridcolor="rgba(100,116,139,0.15)", tickfont=dict(color="#64748B"),
                   titlefont=dict(color="#64748B")),
        yaxis=dict(title="Expected Annual Return", tickformat=".0%",
                   gridcolor="rgba(100,116,139,0.15)", tickfont=dict(color="#64748B"),
                   titlefont=dict(color="#64748B")),
    )
    st.plotly_chart(_fig_ef, use_container_width=True, config={"displayModeBar": False})
    st.caption("Star = optimal portfolio. Diamond = equal-weight baseline. Colour = Sharpe Ratio.")

    st.markdown("---")

    # Optimal Weights
    st.markdown("#### Optimal Allocation")
    _wt_left, _wt_right = st.columns([1, 1])
    with _wt_left:
        _weights_df = pd.DataFrame({
            "Ticker": _valid_tickers,
            "Weight": _opt_weights,
            "Allocation %": [f"{w:.1%}" for w in _opt_weights],
        }).sort_values("Weight", ascending=False).reset_index(drop=True)
        _weights_df.index += 1
        st.dataframe(_weights_df[["Ticker", "Allocation %"]],
                     use_container_width=True, hide_index=False)
    with _wt_right:
        _pie_fig = go.Figure(go.Pie(
            labels=_valid_tickers, values=_opt_weights, hole=0.45,
            marker=dict(colors=["#F59E0B","#22C55E","#3B82F6","#EC4899","#8B5CF6",
                                 "#06B6D4","#EF4444","#84CC16","#F97316","#A78BFA",
                                 "#10B981","#FBBF24","#6366F1","#14B8A6","#FB923C",
                                 "#E11D48","#7C3AED","#0EA5E9","#4ADE80","#FCD34D"][:_n]),
            textfont=dict(size=11, color="#F1F5F9"),
            hovertemplate="%{label}: %{percent}<extra></extra>"
        ))
        _pie_fig.update_layout(
            height=280, margin=dict(l=0,r=0,t=10,b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            legend=dict(font=dict(color="#94A3B8", size=10), bgcolor="rgba(0,0,0,0)"),
            annotations=[dict(text=_opt_objective.split()[0], x=0.5, y=0.5,
                              font=dict(size=11, color="#94A3B8"), showarrow=False)]
        )
        st.plotly_chart(_pie_fig, use_container_width=True, config={"displayModeBar": False})

    st.markdown("---")

    # Correlation Matrix
    st.markdown("#### Correlation Matrix")
    _corr = _returns.corr()
    _corr_fig = go.Figure(go.Heatmap(
        z=_corr.values, x=_valid_tickers, y=_valid_tickers,
        colorscale="RdBu", zmid=0, zmin=-1, zmax=1,
        text=[[f"{v:.2f}" for v in row] for row in _corr.values],
        texttemplate="%{text}", textfont=dict(size=10),
        hovertemplate="%{y} / %{x}: %{z:.2f}<extra></extra>",
        colorbar=dict(tickfont=dict(color="#64748B"), titlefont=dict(color="#64748B"))
    ))
    _corr_fig.update_layout(
        height=max(250, _n * 35),
        margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(tickfont=dict(color="#94A3B8")),
        yaxis=dict(tickfont=dict(color="#94A3B8")),
    )
    st.plotly_chart(_corr_fig, use_container_width=True, config={"displayModeBar": False})
    st.caption("Low or negative correlations (blue) reduce portfolio volatility. "
               "High correlations (red) mean assets move together - less diversification benefit.")

    st.markdown("---")
    st.markdown(
        '<div style="font-size:0.75rem;color:#475569;padding:8px 0">'
        'Disclaimer: Portfolio optimization uses historical price data. Past performance'
        ' does not guarantee future results. For educational purposes only,'
        ' not financial advice. Always do your own research.'
        '</div>', unsafe_allow_html=True)
