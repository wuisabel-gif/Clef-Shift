\version "2.24.0"
\paper { oddFooterMarkup=##f oddHeaderMarkup=##f scoreTitleMarkup=##f ragged-right=##f line-width=14\cm }
\header { tagline=##f }
\score { \new Staff { \clef treble \time 4/4
  c'8 d'8 e'8 f'8 g'8 a'8 b'8 c''8 | d''4 e''4 f''4 g''4 \break
  a'4 b'4 c''4 d''4 | e''8 d''8 c''8 b'8 a'8 g'8 f'8 e'8 |
} \layout {} }
