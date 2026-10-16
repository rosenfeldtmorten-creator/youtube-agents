# Draws one chart as a sequence of PNG frames that reveal the data step by step.
#
#   Rscript charts/chart.R spec.json data.csv out_dir n_frames width height
#
# spec.json  : the scene's chart settings (type, title, y_format, source ...), written by yta/money.py
# data.csv   : columns x, y, group, label (x is a date for "line", a position for "bars", a year for "growth")
# Change the house style in the theme_money() function below; every chart uses it.

suppressPackageStartupMessages({
  library(ggplot2)
  library(jsonlite)
  library(scales)
})

args <- commandArgs(trailingOnly = TRUE)
spec <- fromJSON(args[1])
d <- read.csv(args[2], stringsAsFactors = FALSE)
out_dir <- args[3]
n_frames <- as.integer(args[4])
width_px <- as.integer(args[5])
height_px <- as.integer(args[6])
dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)

# ---------- house style ----------
col_bg     <- "#0E1726"
col_panel  <- "#0E1726"
col_text   <- "#E8EDF5"
col_muted  <- "#93A1B8"
col_grid   <- "#22304A"
palette    <- c("#F2B33D", "#4CC2B3", "#E07A5F", "#9B8CF2", "#7FB3E8")

theme_money <- function() {
  theme_minimal(base_size = 30) +
    theme(
      plot.background  = element_rect(fill = col_bg, colour = NA),
      panel.background = element_rect(fill = col_panel, colour = NA),
      panel.grid.major = element_line(colour = col_grid, linewidth = 0.6),
      panel.grid.minor = element_blank(),
      axis.text        = element_text(colour = col_muted, size = 24),
      axis.title       = element_blank(),
      plot.title       = element_text(colour = col_text, size = 46, face = "bold", margin = margin(b = 14)),
      plot.subtitle    = element_text(colour = col_muted, size = 26, margin = margin(b = 24)),
      plot.caption     = element_text(colour = col_muted, size = 18, hjust = 0, margin = margin(t = 20)),
      legend.position  = "top",
      legend.justification = "left",
      legend.title     = element_blank(),
      legend.text      = element_text(colour = col_text, size = 26),
      plot.margin      = margin(60, 90, 40, 70)
    )
}

y_labels <- function(fmt) {
  switch(fmt,
    usd   = label_dollar(scale_cut = cut_short_scale()),
    pct   = label_percent(accuracy = 1),
    index = label_number(accuracy = 1),
    label_comma(accuracy = 1)
  )
}

value_label <- function(v, fmt) {
  switch(fmt,
    usd   = dollar(v, scale_cut = cut_short_scale(), accuracy = if (abs(v) < 100) 0.01 else 1),
    pct   = percent(v, accuracy = 0.1),
    index = number(v, accuracy = 1),
    comma(v, accuracy = if (abs(v) < 10) 0.1 else 1)
  )
}

title_txt    <- if (!is.null(spec$title_filled)) spec$title_filled else ""
subtitle_txt <- if (!is.null(spec$subtitle)) spec$subtitle else NULL
caption_txt  <- if (!is.null(spec$source_note)) paste("Source:", spec$source_note) else NULL
fmt          <- if (!is.null(spec$y_format)) spec$y_format else "num"
ease         <- function(t) 1 - (1 - t)^3

save_frame <- function(p, i) {
  ggsave(file.path(out_dir, sprintf("frame_%04d.png", i)), p,
         width = width_px / 100, height = height_px / 100, dpi = 100, bg = col_bg)
}

# ---------- chart types ----------

if (spec$type == "line") {
  d$x <- as.Date(d$x)
  groups <- unique(d$group)
  colours <- setNames(palette[seq_along(groups)], groups)
  x_rng <- range(d$x)
  y_rng <- range(c(d$y, if (isTRUE(spec$from_zero)) 0))
  x_pad <- as.numeric(diff(x_rng)) * 0.12
  for (i in seq_len(n_frames)) {
    cutoff <- x_rng[1] + as.numeric(diff(x_rng)) * ease(i / n_frames)
    shown <- d[d$x <= cutoff, ]
    ends <- do.call(rbind, lapply(split(shown, shown$group), function(g) g[which.max(g$x), ]))
    p <- ggplot(shown, aes(x, y, colour = group)) +
      geom_line(linewidth = 2.2) +
      geom_point(data = ends, size = 6) +
      geom_text(data = ends, aes(label = vapply(y, value_label, "", fmt = fmt)),
                hjust = -0.25, size = 9, fontface = "bold", show.legend = FALSE) +
      scale_colour_manual(values = colours) +
      scale_x_date(limits = c(x_rng[1], x_rng[2] + x_pad), date_labels = "%Y") +
      scale_y_continuous(limits = y_rng, labels = y_labels(fmt),
                         trans = if (isTRUE(spec$log)) "log10" else "identity") +
      labs(title = title_txt, subtitle = subtitle_txt, caption = caption_txt) +
      theme_money()
    if (length(groups) == 1) p <- p + theme(legend.position = "none")
    save_frame(p, i)
  }
} else if (spec$type == "bars") {
  d$label <- factor(d$label, levels = d$label[order(d$x)])
  y_max <- max(d$y, 0) * 1.18
  y_min <- min(d$y, 0) * 1.18
  for (i in seq_len(n_frames)) {
    k <- ease(i / n_frames)
    shown <- transform(d, y = y * k)
    p <- ggplot(shown, aes(label, y)) +
      geom_col(fill = palette[1], width = 0.62) +
      geom_text(aes(label = vapply(y, value_label, "", fmt = fmt),
                    vjust = ifelse(y >= 0, -0.5, 1.4)),
                colour = col_text, size = 10, fontface = "bold") +
      scale_y_continuous(limits = c(y_min, y_max), labels = y_labels(fmt)) +
      labs(title = title_txt, subtitle = subtitle_txt, caption = caption_txt) +
      theme_money() +
      theme(axis.text.x = element_text(colour = col_text, size = 26), panel.grid.major.x = element_blank())
    save_frame(p, i)
  }
} else if (spec$type == "growth") {
  # groups: "Money you put in" and "What it grew to"
  years <- sort(unique(d$x))
  y_max <- max(d$y) * 1.1
  for (i in seq_len(n_frames)) {
    cutoff <- min(years) + (max(years) - min(years)) * ease(i / n_frames)
    shown <- d[d$x <= cutoff, ]
    ends <- do.call(rbind, lapply(split(shown, shown$group), function(g) g[which.max(g$x), ]))
    p <- ggplot(shown, aes(x, y, fill = group, colour = group)) +
      geom_area(position = "identity", alpha = 0.35, linewidth = 1.6) +
      geom_text(data = ends, aes(label = vapply(y, value_label, "", fmt = "usd")),
                hjust = 1.05, vjust = -0.6, size = 9, fontface = "bold", show.legend = FALSE) +
      scale_fill_manual(values = c(palette[2], palette[1])) +
      scale_colour_manual(values = c(palette[2], palette[1])) +
      scale_x_continuous(limits = range(years), labels = function(x) paste("Year", x)) +
      scale_y_continuous(limits = c(0, y_max), labels = y_labels("usd")) +
      labs(title = title_txt, subtitle = subtitle_txt, caption = caption_txt) +
      theme_money()
    save_frame(p, i)
  }
} else {
  stop(paste("Unknown chart type:", spec$type))
}
